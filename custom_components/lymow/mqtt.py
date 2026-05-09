"""AWS IoT MQTT-over-WSS client for Lymow.

Wraps paho-mqtt with asyncio bridging.
Signs the connection URL with SigV4 query-string presigning.
One MqttClient instance per device.

Topics:
    subscribe  /device/{thing}/pboutput    → robot state (protobuf)
    subscribe  /device/{thing}/notify-app  → online/offline JSON
    publish    /device/{thing}/pbinput     → commands (protobuf)
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import ssl
import urllib.parse
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import paho.mqtt.client as mqtt

from .protocol import wrap_envelope

_LOGGER = logging.getLogger(__name__)

_TOPIC_PBINPUT   = "/device/{thing}/pbinput"
_TOPIC_PBOUTPUT  = "/device/{thing}/pboutput"
_TOPIC_NOTIFY    = "/device/{thing}/notify-app"

_IOT_SERVICE = "iotdevicegateway"


# ── SigV4 presigned WebSocket URL ─────────────────────────────

def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _presigned_ws_path(
    host: str,
    region: str,
    access_key: str,
    secret_key: str,
    session_token: str | None,
    expires_seconds: int = 86400,
) -> str:
    """Build SigV4 query-string presigned path for AWS IoT MQTT-over-WSS.

    Returns the path component (/mqtt?...) for paho's ws_set_options().
    session_token is appended unsigned after the signature — this is the
    correct AWS IoT idiom (confirmed from working Amplify URL comparison).
    """
    now        = datetime.now(UTC)
    amz_date   = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp  = now.strftime("%Y%m%d")
    scope      = f"{datestamp}/{region}/{_IOT_SERVICE}/aws4_request"

    qs_pairs = {
        "X-Amz-Algorithm":    "AWS4-HMAC-SHA256",
        "X-Amz-Credential":   f"{access_key}/{scope}",
        "X-Amz-Date":         amz_date,
        "X-Amz-Expires":      str(expires_seconds),
        "X-Amz-SignedHeaders": "host",
    }
    canonical_qs = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(qs_pairs.items())
    )

    canonical_req = "\n".join([
        "GET", "/mqtt", canonical_qs,
        f"host:{host}\n", "host",
        hashlib.sha256(b"").hexdigest(),
    ])
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical_req.encode()).hexdigest(),
    ])

    k = _sign(("AWS4" + secret_key).encode(), datestamp)
    k = _sign(k, region)
    k = _sign(k, _IOT_SERVICE)
    k = _sign(k, "aws4_request")
    sig = hmac.new(k, string_to_sign.encode(), hashlib.sha256).hexdigest()

    qs = canonical_qs + f"&X-Amz-Signature={sig}"
    if session_token:
        qs += "&X-Amz-Security-Token=" + urllib.parse.quote(session_token, safe="")
    return f"/mqtt?{qs}"


# ── MQTT client ────────────────────────────────────────────────

class MqttClient:
    """Async-friendly wrapper around paho-mqtt for one Lymow device."""

    def __init__(
        self,
        thing_name: str,
        host: str,
        region: str,
        on_pboutput: Callable[[bytes], None],
        on_notify_app: Callable[[dict], None],
        on_disconnect_cb: Callable[[], None] | None = None,
    ) -> None:
        self._thing_name     = thing_name
        self._host           = host
        self._region         = region
        self._on_pboutput    = on_pboutput
        self._on_notify_app  = on_notify_app
        self._on_disconnect_cb = on_disconnect_cb

        self._client: mqtt.Client | None = None
        self._connected  = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

        self._topic_pboutput = _TOPIC_PBOUTPUT.format(thing=thing_name)
        self._topic_notify   = _TOPIC_NOTIFY.format(thing=thing_name)
        self._topic_pbinput  = _TOPIC_PBINPUT.format(thing=thing_name)

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    async def connect(
        self,
        access_key: str,
        secret_key: str,
        session_token: str | None,
    ) -> None:
        """Sign URL, build paho client, connect, subscribe.

        Returns once CONNACK and SUBACK are both received.
        Raises ConnectionError on timeout.
        """
        self._loop = asyncio.get_running_loop()

        ws_path = _presigned_ws_path(
            host=self._host,
            region=self._region,
            access_key=access_key,
            secret_key=secret_key,
            session_token=session_token,
        )
        _LOGGER.debug("MQTT connecting to %s (thing=%s)", self._host, self._thing_name)

        client_id = f"lymow-ha-{uuid.uuid4().hex[:8]}"
        cli = mqtt.Client(
            client_id=client_id,
            transport="websockets",
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )

        # Build SSL context in executor (blocking disk read for CA certs)
        try:
            import certifi
            ssl_ctx = await self._loop.run_in_executor(
                None, lambda: ssl.create_default_context(cafile=certifi.where())
            )
        except ImportError:
            ssl_ctx = await self._loop.run_in_executor(None, ssl.create_default_context)

        cli.tls_set_context(ssl_ctx)
        cli.ws_set_options(path=ws_path, headers={"Host": self._host})

        cli.on_connect    = self._on_connect
        cli.on_subscribe  = self._on_subscribe
        cli.on_disconnect = self._on_disconnect
        cli.on_message    = self._on_message

        await self._loop.run_in_executor(None, cli.connect, self._host, 443)
        cli.loop_start()
        self._client = cli

        try:
            await asyncio.wait_for(self._connected.wait(), timeout=20.0)
        except asyncio.TimeoutError:
            cli.loop_stop()
            cli.disconnect()
            self._client = None
            raise ConnectionError(
                f"MQTT connect/subscribe timed out for {self._thing_name}"
            )
        _LOGGER.debug("MQTT connected and subscribed for %s", self._thing_name)

    async def disconnect(self) -> None:
        cli = self._client
        self._client = None
        self._connected.clear()
        if cli is None:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, cli.loop_stop)
        cli.disconnect()
        _LOGGER.debug("MQTT disconnected for %s", self._thing_name)

    def publish(self, raw_pbinput: bytes) -> bool:
        """Publish a raw PbInput bytes payload. Returns True if queued OK."""
        if not self._client or not self._connected.is_set():
            return False
        envelope = wrap_envelope(raw_pbinput)
        info = self._client.publish(self._topic_pbinput, envelope, qos=1)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    # ── paho callbacks (run in paho's network thread) ──────────

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: int) -> None:
        if rc != 0:
            _LOGGER.warning("MQTT CONNACK rc=%s for %s", rc, self._thing_name)
            return
        _LOGGER.debug("MQTT CONNACK OK, subscribing…")
        client.subscribe([
            (self._topic_pboutput, 1),
            (self._topic_notify,   1),
        ])

    def _on_subscribe(self, client: Any, userdata: Any, mid: int, granted_qos: Any) -> None:
        # Check for subscription failure (qos >= 0x80)
        if hasattr(granted_qos, '__iter__'):
            failed = [q for q in granted_qos if (q if isinstance(q, int) else getattr(q, 'value', 0)) >= 0x80]
            if failed:
                _LOGGER.error("MQTT subscribe rejected for %s: %s", self._thing_name, failed)
                return
        _LOGGER.debug("MQTT subscribed OK for %s mid=%s", self._thing_name, mid)
        if self._loop:
            self._loop.call_soon_threadsafe(self._connected.set)

    def _on_disconnect(self, client: Any, userdata: Any, rc: int) -> None:
        _LOGGER.debug("MQTT disconnected rc=%s for %s", rc, self._thing_name)
        if self._loop:
            self._loop.call_soon_threadsafe(self._connected.clear)
        if self._on_disconnect_cb and self._loop:
            self._loop.call_soon_threadsafe(self._on_disconnect_cb)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        topic   = msg.topic
        payload = bytes(msg.payload)
        try:
            if topic.endswith("/pboutput"):
                if self._loop:
                    self._loop.call_soon_threadsafe(self._on_pboutput, payload)
            elif topic.endswith("/notify-app"):
                try:
                    data = json.loads(payload.decode("utf-8"))
                    if self._loop:
                        self._loop.call_soon_threadsafe(self._on_notify_app, data)
                except Exception:
                    _LOGGER.debug("Bad notify-app payload: %r", payload[:80])
        except Exception:
            _LOGGER.exception("Error in MQTT message handler for %s", self._thing_name)
