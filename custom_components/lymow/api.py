"""
Lymow async API client.

Auth:  pycognito (USER_SRP_AUTH)
REST:  aiohttp + Cognito AccessToken header (device list, device info,
       clean history, backup map list, S3 download)
MQTT:  paho-mqtt via mqtt.py — all commands and config writes (blade height,
       clean mode, etc.) go through MQTT pbinput only.

IoT shadow writes have been removed entirely.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

try:
    from pycognito import Cognito as _PyCognito
    _HAS_PYCOGNITO = True
except ImportError:
    _HAS_PYCOGNITO = False

from .const import API_ENDPOINTS, COGNITO_CONFIG

_LOGGER = logging.getLogger(__name__)

# Amplify Storage buckets extracted from the official Lymow app config.
S3_BUCKETS: dict[str, str] = {
    "eu-west-1": "lymow-user-data-eu-west-1",
    "ap-southeast-2": "lymow-user-data-ap-southeast-2",
    "us-east-2": "lymow-user-data-us-east-2",
    "ap-east-1": "lymow-user-data-ap-east-1",
}



# ─────────────────────────────────────────────
# SigV4 (used for S3 signed downloads)
# ─────────────────────────────────────────────

def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _signing_key(secret: str, date: str, region: str, service: str) -> bytes:
    k = _sign(("AWS4" + secret).encode(), date)
    k = _sign(k, region)
    k = _sign(k, service)
    return _sign(k, "aws4_request")


def _sigv4_headers(
    method: str,
    url: str,
    payload: bytes,
    service: str,
    region: str,
    access_key: str,
    secret_key: str,
    session_token: str | None = None,
) -> dict[str, str]:
    parsed        = urllib.parse.urlparse(url)
    host          = parsed.netloc
    canonical_uri = parsed.path or "/"
    qs_params     = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    canonical_qs  = urllib.parse.urlencode(sorted(qs_params))

    now        = datetime.now(UTC)
    amz_date   = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    body_hash  = hashlib.sha256(payload).hexdigest()

    hdrs: dict[str, str] = {
        "host":                 host,
        "x-amz-date":           amz_date,
        "x-amz-content-sha256": body_hash,
    }
    if session_token:
        hdrs["x-amz-security-token"] = session_token

    signed_list    = sorted(hdrs)
    canonical_hdrs = "".join(f"{k}:{hdrs[k]}\n" for k in signed_list)
    signed_headers = ";".join(signed_list)

    canonical_req = "\n".join([
        method.upper(), canonical_uri, canonical_qs,
        canonical_hdrs, signed_headers, body_hash,
    ])

    scope          = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical_req.encode()).hexdigest(),
    ])
    sig = hmac.new(
        _signing_key(secret_key, date_stamp, region, service),
        string_to_sign.encode(), hashlib.sha256,
    ).hexdigest()

    return {
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={sig}"
        ),
        "x-amz-date":           amz_date,
        "x-amz-content-sha256": body_hash,
        **({'x-amz-security-token': session_token} if session_token else {}),
    }


# ─────────────────────────────────────────────
# Cognito auth
# ─────────────────────────────────────────────

class CognitoAuth:
    """Cognito SRP login + Identity Pool credential exchange."""

    def __init__(self, region: str, session: aiohttp.ClientSession) -> None:
        if not _HAS_PYCOGNITO:
            raise LymowAuthError("pycognito is required: pip install pycognito")
        self._region  = region
        self._session = session
        self._cfg     = COGNITO_CONFIG[region]

        self.id_token:      str | None = None
        self.access_token:  str | None = None
        self.refresh_token: str | None = None
        self._token_expiry: datetime | None = None

        self.identity_id:       str | None = None
        self.access_key_id:     str | None = None
        self.secret_access_key: str | None = None
        self.session_token:     str | None = None
        self._creds_expiry:     datetime | None = None

        self._email:    str | None = None
        self._password: str | None = None

    # ── SRP login ──────────────────────────────────────────────

    async def login(self, email: str, password: str) -> None:
        _LOGGER.debug("SRP login: %s @ %s", email, self._region)

        def _do_srp() -> tuple[str, str, str]:
            u = _PyCognito(
                user_pool_id=self._cfg["user_pool_id"],
                client_id=self._cfg["client_id"],
                user_pool_region=self._region,
                username=email,
            )
            u.authenticate(password=password)
            return u.id_token, u.access_token, u.refresh_token

        try:
            loop = asyncio.get_running_loop()
            id_t, acc_t, ref_t = await loop.run_in_executor(None, _do_srp)
        except Exception as e:
            raise LymowAuthError(f"SRP login failed: {e}") from e

        self.id_token      = id_t
        self.access_token  = acc_t
        self.refresh_token = ref_t
        self._token_expiry = datetime.now(UTC) + timedelta(hours=1)
        self._email        = email
        self._password     = password

    async def refresh(self) -> None:
        if not self.refresh_token or not self._email:
            raise LymowAuthError("No refresh token — re-login required")

        def _do_refresh() -> tuple[str, str]:
            u = _PyCognito(
                user_pool_id=self._cfg["user_pool_id"],
                client_id=self._cfg["client_id"],
                user_pool_region=self._region,
                username=self._email,
                id_token=self.id_token,
                refresh_token=self.refresh_token,
                access_token=self.access_token,
            )
            u.renew_access_token()
            return u.id_token, u.access_token

        try:
            loop = asyncio.get_running_loop()
            id_t, acc_t = await loop.run_in_executor(None, _do_refresh)
        except Exception as e:
            raise LymowAuthError(f"Token refresh failed: {e}") from e

        self.id_token      = id_t
        self.access_token  = acc_t
        self._token_expiry = datetime.now(UTC) + timedelta(hours=1)

    # ── Identity Pool → AWS credentials ────────────────────────

    async def get_aws_credentials(self) -> None:
        if not self.id_token:
            raise LymowAuthError("No IdToken — call login() first")

        logins = {
            f"cognito-idp.{self._region}.amazonaws.com/{self._cfg['user_pool_id']}": self.id_token
        }
        base_url  = f"https://cognito-identity.{self._region}.amazonaws.com/"
        base_hdrs = {"Content-Type": "application/x-amz-json-1.1"}

        async with self._session.post(
            base_url,
            json={"IdentityPoolId": self._cfg["identity_pool_id"], "Logins": logins},
            headers={**base_hdrs, "X-Amz-Target": "AWSCognitoIdentityService.GetId"},
        ) as r:
            data = await r.json(content_type=None)
            if r.status != 200:
                raise LymowAuthError(f"GetId failed ({r.status}): {data}")
            self.identity_id = data["IdentityId"]

        async with self._session.post(
            base_url,
            json={"IdentityId": self.identity_id, "Logins": logins},
            headers={**base_hdrs, "X-Amz-Target": "AWSCognitoIdentityService.GetCredentialsForIdentity"},
        ) as r:
            data = await r.json(content_type=None)
            if r.status != 200:
                raise LymowAuthError(f"GetCredentialsForIdentity failed ({r.status}): {data}")
            c = data["Credentials"]

        self.access_key_id     = c["AccessKeyId"]
        self.secret_access_key = c["SecretKey"]
        self.session_token     = c["SessionToken"]
        exp = c["Expiration"]
        self._creds_expiry = (
            datetime.fromtimestamp(exp, UTC) if isinstance(exp, (int, float)) else None
        )
        _LOGGER.debug("AWS credentials OK, expire: %s", self._creds_expiry)

    # ── Lifecycle ───────────────────────────────────────────────

    def _tokens_expiring(self) -> bool:
        if not self._token_expiry:
            return True
        return datetime.now(UTC) >= (self._token_expiry - timedelta(minutes=5))

    def _creds_expiring(self) -> bool:
        if not self._creds_expiry:
            return True
        return datetime.now(UTC) >= (self._creds_expiry - timedelta(minutes=10))

    async def ensure_valid(self, email: str | None = None, password: str | None = None) -> None:
        _email    = email    or self._email
        _password = password or self._password

        if self._tokens_expiring():
            if self.refresh_token:
                try:
                    await self.refresh()
                except LymowAuthError:
                    if _email and _password:
                        await self.login(_email, _password)
                    else:
                        raise
            elif _email and _password:
                await self.login(_email, _password)
            else:
                raise LymowAuthError("Tokens expired and no credentials available")

        if self._creds_expiring():
            await self.get_aws_credentials()

    # ── Serialization ───────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id_token":          self.id_token,
            "access_token":      self.access_token,
            "refresh_token":     self.refresh_token,
            "access_key_id":     self.access_key_id,
            "secret_access_key": self.secret_access_key,
            "session_token":     self.session_token,
            "_email":            self._email,
        }

    def from_dict(self, d: dict) -> None:
        self.id_token          = d.get("id_token")
        self.access_token      = d.get("access_token")
        self.refresh_token     = d.get("refresh_token")
        self.access_key_id     = d.get("access_key_id")
        self.secret_access_key = d.get("secret_access_key")
        self.session_token     = d.get("session_token")
        self._email            = d.get("_email")


# ─────────────────────────────────────────────
# Lymow REST client (no shadow/IoT HTTPS)
# ─────────────────────────────────────────────

class LymowClient:
    """REST API client — device info, S3 map downloads. Commands via MQTT."""

    def __init__(self, region: str, auth: CognitoAuth, session: aiohttp.ClientSession) -> None:
        self._region  = region
        self._auth    = auth
        self._session = session
        self._ep      = API_ENDPOINTS[region]

    # ── Auth helpers ────────────────────────────────────────────

    def _rest_headers(self) -> dict:
        return {
            "Content-Type":    "application/json",
            "Accept-Encoding": "gzip, deflate, br",
            "Authorization":   self._auth.access_token,
        }

    # ── REST API ────────────────────────────────────────────────

    async def _api_get(self, api: str, path: str) -> Any:
        url = self._ep[api] + path
        async with self._session.get(url, headers=self._rest_headers()) as r:
            text = await r.text()
            if r.status >= 400:
                _LOGGER.warning("GET %s%s → %s: %s", api, path, r.status, text)
                return None
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text

    async def get_device_list(self) -> list[dict]:
        data = await self._api_get("deviceBindingApi", "/device-list-query?p=validation")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in ("data", "items", "devices", "list"):
                if isinstance(data.get(k), list):
                    return data[k]
        return []

    async def get_device_info(self, thing_name: str) -> dict:
        data = await self._api_get(
            "deviceProfileApi", f"/get-device-info?deviceThingName={thing_name}"
        )
        return data or {}

    async def get_device_feature(self, thing_name: str) -> dict:
        data = await self._api_get(
            "deviceProfileApi", f"/get-device-feature?deviceThingName={thing_name}"
        )
        return data or {}

    async def get_clean_history(self, thing_name: str, page: int = 1, size: int = 10) -> dict | list[dict]:
        """Return raw clean-history payload.

        The API can return a dict with clean_history, clean_summary,
        total_records, page and has_more. Keep that structure instead of
        flattening it, so Home Assistant can expose summary sensors.
        """
        data = await self._api_get(
            "s3Api",
            f"/get-clean-history-collect?deviceThingName={thing_name}&page={page}&pageSize={size}",
        )
        if isinstance(data, (dict, list)):
            return data
        return {}

    async def get_backup_map(self, thing_name: str) -> dict | None:
        return await self._api_get("s3Api", f"/get-backup-map?deviceThingName={thing_name}")

    async def download_s3_object(self, key: str) -> bytes | None:
        """Download a private object from the official Amplify Storage bucket.

        Backup map files returned by ``get_backup_map`` are S3 keys, for example
        ``device_xxx/map/map.pb``. The official app downloads them with
        Amplify Storage.getUrl(), using bucket ``lymow-user-data-<region>``.
        This method performs the same GET with SigV4 headers and the Cognito
        Identity temporary credentials already stored in ``CognitoAuth``.
        """
        bucket = S3_BUCKETS.get(self._region)
        if not bucket:
            _LOGGER.warning("No Lymow S3 bucket configured for region %s", self._region)
            return None
        if not (self._auth.access_key_id and self._auth.secret_access_key and self._auth.session_token):
            await self._auth.get_aws_credentials()

        encoded_key = urllib.parse.quote(key, safe="/~")
        url = f"https://{bucket}.s3.{self._region}.amazonaws.com/{encoded_key}"
        hdrs = _sigv4_headers(
            method="GET",
            url=url,
            payload=b"",
            service="s3",
            region=self._region,
            access_key=self._auth.access_key_id,
            secret_key=self._auth.secret_access_key,
            session_token=self._auth.session_token,
        )
        try:
            async with self._session.get(url, headers=hdrs) as r:
                body = await r.read()
                if r.status >= 400:
                    _LOGGER.warning(
                        "S3 download failed for %s/%s: %s %s",
                        bucket, key, r.status, body[:500].decode("utf-8", errors="replace"),
                    )
                    return None
                return body
        except Exception as e:
            _LOGGER.warning("S3 download error for %s: %s", key, e)
            return None

    async def get_download_url(self, file_key: str) -> dict:
        """Legacy/debug endpoint. Not used for backup maps."""
        key = urllib.parse.quote(file_key, safe="")
        data = await self._api_get("s3Api", f"/get-download-url?key={key}")
        return data or {}

    async def check_update(self, thing_name: str) -> dict:
        data = await self._api_get("checkUpdateApi", f"/check-update?deviceThingName={thing_name}")
        return data or {}


# ─────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────

class LymowError(Exception):
    """Base Lymow error."""

class LymowAuthError(LymowError):
    """Authentication error."""

class LymowAPIError(LymowError):
    """API call error."""