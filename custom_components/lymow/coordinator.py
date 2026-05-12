"""DataUpdateCoordinator for Lymow — MQTT push-driven.

State arrives via MQTT /pboutput broadcasts.
Commands are published to /pbinput as protobuf messages.

Startup + periodic refresh:
  On connect:
    build_initial_query_packets() → map, path, schedules, cleaning info,
                                      appConnect, debug profile/WiFi, robot config, net detail, WiFi/4G, RTK L1/L2

  Every _REFRESH_INTERVAL (default 90s):
    build_refresh_query_packets()
    (ensures IP address, signal info and RTK stay current without the app open)

  On MQTT disconnect:
    Refresh AWS credentials (they expire after ~1h causing the disconnect)
    Re-create paho connection with a new presigned URL
    Re-fire startup queries

REST poll every 15 min: device online/offline fallback.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import CognitoAuth, LymowClient, LymowError
from .const import (
    DOMAIN,
    F_DEVICE_STATE,
    WORK_STATUS_DOCKING,
    WORK_STATUS_OFFLINE,
    WORK_STATUS_PAUSE_DOCKING,
)
from .mqtt import MqttClient
from .protocol import (
    USER_CTRL_CLEAN,
    USER_CTRL_DOCK,
    USER_CTRL_FORCE_REINIT,
    USER_CTRL_PAUSE,
    USER_CTRL_PAUSE_DOCK,
    USER_CTRL_RECHARGE_DOCK,
    USER_CTRL_RESUME,
    USER_CTRL_RESUME_DOCK,
    build_initial_query_packets,
    build_refresh_query_packets,
    encode_query_robot_config,
    decode_pboutput_envelope,
    decode_pbmap,
    encode_start_zones,
    encode_userctrl,
)
from .state import derive_current_zone, robot_gps_from_state
from .state_matrix import lookup as lookup_state_row

_LOGGER = logging.getLogger(__name__)

_REST_POLL_INTERVAL = timedelta(minutes=15)
_REFRESH_INTERVAL   = 90          # seconds — periodic config/net/RTK refresh
_RECONNECT_DELAY    = 5           # seconds — wait before reconnect attempt
_WATCHDOG_TIMEOUT   = 5.0


class LymowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Push-only coordinator for a single Lymow robot."""

    def __init__(
        self,
        hass: HomeAssistant,
        auth: CognitoAuth,
        client: LymowClient,
        thing_name: str,
        region: str,
        email: str,
        password: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{thing_name}",
            update_interval=None,   # push-only
        )
        self.auth       = auth
        self.client     = client
        self.thing_name = thing_name
        self._region    = region
        self._email     = email
        self._password  = password
        self._client_uuid = str(uuid.uuid4())

        self._state: dict[str, Any] = {}
        self.device_info_data: dict = {}
        self.history: list[dict]    = []

        self._mow_path: list[tuple[float, float]] = []
        self._mow_session_active: bool = False

        self._rest_online: bool    = False
        self._last_mqtt_ts: float  = 0.0
        self._prev_work_status: int | None = None
        self._shutting_down        = False

        self.mqtt: MqttClient | None = None

        self._rest_poll_task:    asyncio.Task | None = None
        self._refresh_task:      asyncio.Task | None = None
        self._reconnect_task:    asyncio.Task | None = None

        self._state_event = asyncio.Event()

    # ── Setup / teardown ────────────────────────────────────────

    async def async_setup(self) -> None:
        """Authenticate, load REST/S3 map fallback, connect MQTT, fire startup queries."""
        self._shutting_down = False
        await self.auth.ensure_valid(self._email, self._password)

        # REST metadata first: device_info gives IP/firmware/location fallback.
        await self._do_rest_poll()

        # Load S3 backup map before MQTT. This gives the SVG camera a full
        # zone catalog even if MQTT QUERY_MAP only returns a summary without
        # polygon points.
        await self._load_backup_map()

        await self._connect_mqtt()

        self._rest_poll_task = self.hass.async_create_background_task(
            self._rest_poll_loop(), name=f"lymow_rest_poll_{self.thing_name}"
        )
        self._refresh_task = self.hass.async_create_background_task(
            self._refresh_loop(), name=f"lymow_refresh_{self.thing_name}"
        )

    async def async_shutdown(self) -> None:
        """Disconnect MQTT and cancel all background tasks."""
        self._shutting_down = True
        for task_attr in ("_rest_poll_task", "_refresh_task", "_reconnect_task"):
            task = getattr(self, task_attr)
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                setattr(self, task_attr, None)
        if self.mqtt:
            await self.mqtt.disconnect()
            self.mqtt = None

    async def _connect_mqtt(self) -> None:
        """Create and connect a new MqttClient with current credentials."""
        # Disconnect old client if any
        if self.mqtt:
            try:
                await self.mqtt.disconnect()
            except Exception:
                pass
            self.mqtt = None

        self.mqtt = MqttClient(
            thing_name=self.thing_name,
            host=self.client._ep["iotDomain"].replace("https://", "").rstrip("/"),
            region=self._region,
            on_pboutput=self._handle_pboutput,
            on_notify_app=self._handle_notify_app,
            on_disconnect_cb=self._handle_disconnect,
        )
        await self.mqtt.connect(
            access_key=self.auth.access_key_id,
            secret_key=self.auth.secret_access_key,
            session_token=self.auth.session_token,
        )
        _LOGGER.debug("MQTT connected for %s — firing startup queries", self.thing_name)
        self._fire_startup_queries()

    def _fire_startup_queries(self) -> None:
        """Publish all startup queries. Also called after reconnect."""
        for raw in build_initial_query_packets(client_uuid=self._client_uuid):
            self._publish(raw)
        # Robot only responds to robotConfig query after being online for a few seconds
        self.hass.async_create_task(self._delayed_robot_config(1))
        self.hass.async_create_task(self._delayed_robot_config(5))

    def _fire_refresh_queries(self) -> None:
        """Periodic refresh — keeps IP, signal, RTK and config up to date."""
        for raw in build_refresh_query_packets(client_uuid=self._client_uuid):
            self._publish(raw)
    
    async def _delayed_robot_config(self, delay: int) -> None:
        """Send robot config query with delay — mirrors app behavior (1s + 5s)."""
        self._publish(encode_query_robot_config())

    # ── Properties ──────────────────────────────────────────────

    @property
    def work_status(self) -> int:
        return self._state.get("workStatus", WORK_STATUS_OFFLINE)

    @property
    def is_online(self) -> bool:
        if not self._state:
            return False
        return (
            self._state.get("isOnline", False)
            or self._state.get(F_DEVICE_STATE) == "online"
            or self.work_status not in (WORK_STATUS_OFFLINE, -1)
        )
    
    @property
    def mow_path(self) -> list[tuple[float, float]]:
        """ENU points accumulated during the current/last mowing session."""
        return self._mow_path

    @property
    def state_dict(self) -> dict[str, Any]:
        """Compatibility alias used by helper entities."""
        return self._state

    def _merge_state(self, new_state: dict[str, Any]) -> None:
        """Merge MQTT/REST state without losing sticky subfields.

        Many PbOutput messages are partial. Dict submessages are merged so a
        packet carrying just one field does not wipe previously-known IP, map,
        RTK or configuration details. btMap.enuBasePoint is kept sticky because
        QUERY_PATH/QUERY_MAP can share the same branch.
        """
        for k, v in new_state.items():
            if isinstance(v, dict) and isinstance(self._state.get(k), dict):
                if k == "btMap":
                    old = self._state[k]
                    # Preserve ENU anchor and zone catalog when a partial path
                    # response arrives without the full map payload.
                    if "enuBasePoint" in old and "enuBasePoint" not in v:
                        v = {**v, "enuBasePoint": old["enuBasePoint"]}
                    if old.get("zones") and not v.get("zones"):
                        v = {**v, "zones": old["zones"]}
                    if old.get("zone_count") and not v.get("zone_count"):
                        v = {**v, "zone_count": old["zone_count"]}
                self._state[k].update(v)
            else:
                self._state[k] = v

        btmap = self._state.get("btMap") or {}
        if isinstance(btmap, dict) and isinstance(btmap.get("enuBasePoint"), dict):
            self._state["enu_base_point"] = btmap["enuBasePoint"]

    def _derive_state(self) -> None:
        """Derive convenience fields used by HA entities."""
        gps = robot_gps_from_state(self._state)
        if gps is not None:
            self._state["derivedLatitude"] = gps[0]
            self._state["derivedLongitude"] = gps[1]
            # Keep top-level aliases useful for sensors, but do not overwrite
            # explicit robotLlaCoords if the firmware ever emits them.
            self._state.setdefault("latitude", gps[0])
            self._state.setdefault("longitude", gps[1])

        zone = derive_current_zone(self._state)
        if zone:
            self._state["currentZone"] = zone

        # Flatten runTimeConfig from btMap to top-level (blade height sensor)
        btmap = self._state.get("btMap") or {}
        import logging
        _LOGGER.warning(
            "DEBUG derive_state: cutHeight_top=%s btMap_cutHeight=%s btMap_keys=%s runTimeConfig=%s",
            self._state.get("cutHeight"),
            btmap.get("cutHeight"),
            list(btmap.keys())[:10],
            btmap.get("runTimeConfig"),
        )
        for k in ("cutHeight", "cutSpeed", "moveSpeed"):
            if btmap.get(k) is not None and self._state.get(k) is None:
                self._state[k] = btmap[k]


    # ── Inbound MQTT handlers ────────────────────────────────────

    def _handle_pboutput(self, raw_envelope: bytes) -> None:
        import time
        self._last_mqtt_ts = time.monotonic()

        new_state = decode_pboutput_envelope(raw_envelope)
        if not new_state:
            _LOGGER.debug("Empty pboutput decode for %s", self.thing_name)
            return

        self._merge_state(new_state)
        self._derive_state()

        if (ws := new_state.get("workStatus")) is not None:
            self._prev_work_status = ws

        # ── Mow path tracking ──────────────────────────────────
        ws = new_state.get("workStatus")
        if ws is not None:
            is_mowing = new_state.get("robotStatus") == 2  # CLEANING

            if is_mowing:
                self._mow_session_active = True
                robot = (
                    new_state.get("pose")
                    or new_state.get("robotLoc")
                    or self._state.get("pose")
                    or self._state.get("robotLoc")
                )
                if isinstance(robot, dict):
                    x, y = robot.get("x"), robot.get("y")
                    if x is not None and y is not None:
                        pt = (round(float(x), 3), round(float(y), 3))
                        if not self._mow_path or self._mow_path[-1] != pt:
                            self._mow_path.append(pt)

            # Reset SOLO quando è al dock (sessione terminata)
            robot_status = new_state.get("robotStatus")
            if robot_status in (0, 5, 12):   # NONE, CHARGING, CHARGING_FULL
                self._mow_path = []
                self._mow_session_active = False
            elif robot_status in (1, 3, 8, 4, 10):  # WAITING, PAUSE, RESUME, DOCKING, PAUSE_DOCKING
                self._mow_session_active = False     # congela ma preserva path

        _LOGGER.debug(
            "State update %s: workStatus=%s battery=%s",
            self.thing_name,
            self._state.get("workStatus"),
            self._state.get("battery"),
        )
        self._state_event.set()
        self.async_set_updated_data(self._state)

    def _handle_notify_app(self, payload: dict) -> None:
        rs = payload.get("robotState")
        if rs == "online":
            self._rest_online = True
            self._state.update({"deviceState": "online", "isOnline": True})
        elif rs == "offline":
            self._rest_online = False
            self._state.update({"deviceState": "offline", "isOnline": False})
        self.async_set_updated_data(self._state)

    def _handle_disconnect(self) -> None:
        """Called when paho reports a disconnect.

        AWS IoT temporary credentials expire after ~1 hour, causing the broker
        to close the connection. We must refresh credentials and reconnect with
        a new presigned URL — paho's built-in reconnect cannot do this.
        """
        if self._shutting_down:
            return
        _LOGGER.warning(
            "MQTT disconnected for %s — will refresh credentials and reconnect",
            self.thing_name,
        )
        # Schedule reconnect in the HA event loop (we're in paho's thread here)
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = self.hass.async_create_background_task(
                self._reconnect_with_fresh_creds(),
                name=f"lymow_reconnect_{self.thing_name}"
            )

    async def _reconnect_with_fresh_creds(self) -> None:
        """Refresh AWS credentials and re-create the MQTT connection."""
        await asyncio.sleep(_RECONNECT_DELAY)
        if self._shutting_down:
            return
        try:
            _LOGGER.info("Refreshing AWS credentials for %s", self.thing_name)
            await self.auth.ensure_valid(self._email, self._password)
            await self._connect_mqtt()
            _LOGGER.info("MQTT reconnected for %s", self.thing_name)
        except Exception:
            _LOGGER.exception("MQTT reconnect failed for %s — will retry on next disconnect", self.thing_name)

    # ── Background loops ─────────────────────────────────────────

    async def _refresh_loop(self) -> None:
        """Periodically query config/net/RTK to keep state current."""
        while True:
            try:
                await asyncio.sleep(_REFRESH_INTERVAL)
                if self.mqtt and self.mqtt.is_connected:
                    _LOGGER.debug("Periodic refresh queries for %s", self.thing_name)
                    self._fire_refresh_queries()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Refresh loop error for %s", self.thing_name)

    async def _rest_poll_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(_REST_POLL_INTERVAL.total_seconds())
                await self._do_rest_poll()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("REST poll failed for %s", self.thing_name)

    def _backup_map_label(self, item: dict[str, Any]) -> str:
        """Human-readable label for a backup map select option."""
        name = (item.get("name") or "").strip()
        map_file = item.get("map_file") or ""
        filename = map_file.rsplit("/", 1)[-1] if map_file else "unknown"

        # Keep labels unique/readable. Many backup names can be blank.
        if name:
            return f"{name} · {filename}"
        return filename

    def _backup_map_options(self) -> list[str]:
        """Return labels for available backup maps."""
        maps = self._state.get("backupMapList") or []
        if not isinstance(maps, list):
            return []
        return [
            self._backup_map_label(item)
            for item in maps
            if isinstance(item, dict) and isinstance(item.get("map_file"), str)
        ]

    def _backup_map_item_for_option(self, option: str) -> dict[str, Any] | None:
        """Find backup map list item matching a select option label."""
        maps = self._state.get("backupMapList") or []
        if not isinstance(maps, list):
            return None
        for item in maps:
            if isinstance(item, dict) and self._backup_map_label(item) == option:
                return item
        return None

    @property
    def backup_map_options(self) -> list[str]:
        return self._backup_map_options()

    @property
    def current_backup_map_option(self) -> str | None:
        loaded = self._state.get("loadedBackupMap")
        if isinstance(loaded, dict):
            return self._backup_map_label(loaded)
        return None

    async def async_select_backup_map(self, option: str) -> bool:
        """Select and load a backup map from the HA select entity."""
        item = self._backup_map_item_for_option(option)
        if not item:
            _LOGGER.warning("Unknown Lymow backup map option for %s: %s", self.thing_name, option)
            return False
        map_file = item.get("map_file")
        if not isinstance(map_file, str):
            return False
        await self._load_backup_map(selected_map_file=map_file)
        return self._state.get("backupMapDownloadError") is None

    async def async_refresh_backup_maps(self) -> None:
        """Refresh backup map list and keep current/default map loaded."""
        await self._load_backup_map(selected_map_file=self._state.get("selectedBackupMapFile"))

    async def _load_backup_map(self, selected_map_file: str | None = None) -> None:
        """Load selected/default backup map from S3 and merge it into state.

        get_backup_map returns S3 keys such as ``device_xxx/map/map.pb``.
        The downloaded object is a standalone PbMap message, not a PbOutput and
        not a PbBtMap wrapper.

        If selected_map_file is None:
          - keep previously selectedBackupMapFile if present;
          - otherwise prefer current map.pb;
          - otherwise first valid backup map.
        """
        try:
            await self.auth.ensure_valid(self._email, self._password)
            backup = await self.client.get_backup_map(self.thing_name)
            map_list = (backup or {}).get("mapList") if isinstance(backup, dict) else None
            if not isinstance(map_list, list) or not map_list:
                self._merge_state({
                    "backupMapList": [],
                    "backupMapOptions": [],
                    "backupMapDownloadError": "empty_map_list",
                })
                self.async_set_updated_data(self._state)
                return

            selected = None

            desired_file = selected_map_file or self._state.get("selectedBackupMapFile")
            if desired_file:
                selected = next(
                    (
                        item for item in map_list
                        if isinstance(item, dict) and item.get("map_file") == desired_file
                    ),
                    None,
                )

            # Prefer current map.pb by default.
            if selected is None:
                selected = next(
                    (
                        item for item in map_list
                        if (
                            isinstance(item, dict)
                            and isinstance(item.get("map_file"), str)
                            and item["map_file"].endswith("/map.pb")
                        )
                    ),
                    None,
                )

            if selected is None:
                selected = next(
                    (
                        item for item in map_list
                        if isinstance(item, dict) and isinstance(item.get("map_file"), str)
                    ),
                    None,
                )

            options = [
                self._backup_map_label(item)
                for item in map_list
                if isinstance(item, dict) and isinstance(item.get("map_file"), str)
            ]

            if not selected:
                self._merge_state({
                    "backupMapList": map_list,
                    "backupMapOptions": options,
                    "backupMapDownloadError": "no_valid_map_file",
                })
                self.async_set_updated_data(self._state)
                return

            map_file = selected["map_file"]
            self._merge_state({
                "backupMapList": map_list,
                "backupMapOptions": options,
                "selectedBackupMapFile": map_file,
                "selectedBackupMapOption": self._backup_map_label(selected),
                "backupMapDownloadError": None,
            })
            self.async_set_updated_data(self._state)

            raw = await self.client.download_s3_object(map_file)
            if not raw:
                self._merge_state({
                    "backupMapList": map_list,
                    "backupMapOptions": options,
                    "loadedBackupMap": selected,
                    "backupMapDownloadError": "download_failed",
                })
                self.async_set_updated_data(self._state)
                return

            decoded = decode_pbmap(raw)
            if not decoded:
                self._merge_state({
                    "backupMapList": map_list,
                    "backupMapOptions": options,
                    "loadedBackupMap": selected,
                    "backupMapBytes": len(raw),
                    "backupMapDownloadError": "decode_failed",
                })
                self.async_set_updated_data(self._state)
                return
            
            _LOGGER.warning(
                "DEBUG map decode: keys=%s cutHeight=%s runTimeConfig=%s",
                list(decoded.keys()),
                decoded.get("cutHeight"),
                decoded.get("runTimeConfig"),
            )

            state_update: dict[str, Any] = {
                "backupMapList": map_list,
                "backupMapOptions": options,
                "selectedBackupMapFile": map_file,
                "selectedBackupMapOption": self._backup_map_label(selected),
                "loadedBackupMap": selected,
                "backupMapBytes": len(raw),
                "backupMapDecodedZones": len(decoded.get("zones") or []),
                "backupMapZonesWithPoints": sum(1 for z in (decoded.get("zones") or []) if z.get("points")),
                "backupMapDownloadError": None,
                "btMap": decoded,
            }
            if decoded.get("enuBasePoint"):
                state_update["enu_base_point"] = decoded["enuBasePoint"]
            if decoded.get("chargingStationLoc"):
                state_update["chargingStationLoc"] = decoded["chargingStationLoc"]
            # Flatten runTimeConfig values to state root for blade_height sensor
            for k in ("cutHeight", "cutSpeed", "moveSpeed"):
                if decoded.get(k) is not None:
                    state_update[k] = decoded[k]

            self._merge_state(state_update)
            self._derive_state()

            _LOGGER.info(
                "Loaded Lymow backup map for %s: option=%s zones=%s bytes=%s key=%s",
                self.thing_name,
                self._backup_map_label(selected),
                decoded.get("zone_count"),
                len(raw),
                map_file,
            )
            self.async_set_updated_data(self._state)

        except Exception:
            _LOGGER.debug("Backup map load failed for %s", self.thing_name, exc_info=True)
            self._merge_state({"backupMapDownloadError": "exception"})
            self.async_set_updated_data(self._state)

    async def _do_rest_poll(self) -> None:
        try:
            await self.auth.ensure_valid(self._email, self._password)
            info = await self.client.get_device_info(self.thing_name)
            if info:
                self.device_info_data = info
                ds = info.get("deviceState") or info.get("device_state") or "offline"
                self._rest_online = ds == "online"

                rest_state: dict[str, Any] = {
                    "deviceInfoRest": info,
                    "deviceState": ds,
                    "isOnline": self._rest_online,
                }
                for src, dst in [
                    ("ipAddress", "ipAddress"),
                    ("sn", "sn"),
                    ("macAddress", "macAddress"),
                    ("simId", "simId"),
                    ("mcuVersion", "fwVersion"),
                    ("mcuVersion", "appFwVersion"),
                    ("softwareVersion", "mcuVersion"),
                    ("softwareVersion", "softwareVersion"),
                ]:
                    if val := info.get(src):
                        rest_state[dst] = val.strip() if isinstance(val, str) else val

                loc = info.get("robotLocation")
                if isinstance(loc, list) and len(loc) >= 2:
                    rest_state["robotLocation"] = loc
                    rest_state["latitude"] = loc[0]
                    rest_state["longitude"] = loc[1]

                self._merge_state(rest_state)

                # Lightweight feature data: theft/find settings, notification switches.
                try:
                    features = await self.client.get_device_feature(self.thing_name)
                    if features:
                        self._merge_state({
                            "deviceFeature": features,
                            "theftDetectionSwitch": features.get("theftDetectionSwitch"),
                            "findRobotSwitch": features.get("findRobotSwitch"),
                            "mobileNotificationSwitch": features.get("mobileNotificationSwitch"),
                            "theftLock": features.get("theftLock"),
                        })
                except Exception:
                    _LOGGER.debug("Feature poll error for %s", self.thing_name, exc_info=True)

                self._derive_state()
            else:
                self._rest_online = False
        except Exception:
            _LOGGER.debug("REST poll error for %s", self.thing_name, exc_info=True)

        # ── Firmware update check (outside main try so REST errors don't skip it)
        try:
            update_info = await self.client.check_update(self.thing_name)
            if isinstance(update_info, dict):
                latest = (
                    update_info.get("latestFw")
                    or update_info.get("latest_fw")
                    or update_info.get("version")
                )
                note = (
                    update_info.get("releaseNote")
                    or update_info.get("release_note")
                    or update_info.get("releaseNotes")
                    or ""
                )
                if latest:
                    self._merge_state({"latestFw": latest, "releaseNote": note})
        except Exception:
            _LOGGER.debug("Firmware update check failed for %s", self.thing_name, exc_info=True)

        self.async_set_updated_data(self._state)

    # ── Publish helpers ──────────────────────────────────────────

    def _publish(self, raw: bytes) -> bool:
        if not self.mqtt or not self.mqtt.is_connected:
            return False
        return self.mqtt.publish(raw)

    async def _wait_state_update(self, timeout: float = _WATCHDOG_TIMEOUT) -> bool:
        self._state_event.clear()
        try:
            await asyncio.wait_for(self._state_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def _state_row(self):
        return lookup_state_row(
            work_status=self._state.get("workStatus"),
            robot_status=self._state.get("robotStatus"),
            is_recharging=self._state.get("isRecharging"),
        )

    # ── Commands ─────────────────────────────────────────────────

    async def async_start_mow(self, zone_ids: list[str] | None = None) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        if zone_ids:
            raw = encode_start_zones(zone_ids)
        else:
            row = self._state_row()
            raw = encode_userctrl(row.start_mowing or USER_CTRL_CLEAN)
        ok  = self._publish(raw)
        await self._wait_state_update()
        return ok

    async def async_pause(self) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        row = self._state_row()
        ctrl = row.pause or (USER_CTRL_PAUSE_DOCK if self.work_status in (WORK_STATUS_DOCKING, WORK_STATUS_PAUSE_DOCKING) else USER_CTRL_PAUSE)
        ok   = self._publish(encode_userctrl(ctrl))
        await self._wait_state_update()
        return ok

    async def async_resume(self) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        ctrl = USER_CTRL_RESUME_DOCK if self.work_status == WORK_STATUS_PAUSE_DOCKING else USER_CTRL_RESUME
        ok   = self._publish(encode_userctrl(ctrl))
        await self._wait_state_update()
        return ok

    async def async_dock(self) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        row = self._state_row()
        ok = self._publish(encode_userctrl(row.dock or USER_CTRL_RECHARGE_DOCK))
        await self._wait_state_update()
        return ok

    async def async_dock_cancel_task(self) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        ok = self._publish(encode_userctrl(USER_CTRL_DOCK))
        await self._wait_state_update()
        return ok

    async def async_stop(self) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        ok = self._publish(encode_userctrl(USER_CTRL_FORCE_REINIT))
        await self._wait_state_update()
        return ok

    async def async_set_blade_height(self, height_mm: int) -> None:
        """Set global blade cut height via PbMap.runTimeConfig."""
        from .protocol import encode_set_cut_height
        self._publish(encode_set_cut_height(height_mm))
        # Aggiorna lo stato locale immediatamente (ottimistic update)
        if self.data:
            self.data["cutHeight"] = height_mm
            btmap = self.data.get("btMap") or {}
            btmap["cutHeight"] = height_mm
            self.data["btMap"] = btmap
        self.async_update_listeners()

    async def async_set_clean_mode(self, mode: str) -> bool:
        """Set global clean mode via PbInput.robotConfig (MQTT only).

        PbInput.robotConfig = field 13, PbRobotConfig.cleanMode = field 7.
        """
        from .protocol import _enc_i32, _enc_len, PB_VERSION_4_9
        _CLEAN_MODE_INT = {
            "ZIGZAG_MODE": 1, "CHESS_BOARD_MODE": 2,
            "PERIMETER_LAPS_ONLY_MODE": 3, "ADAPTIVE_ZIGZAG_MODE": 4,
        }
        mode_int = _CLEAN_MODE_INT.get(mode)
        if mode_int is None:
            _LOGGER.warning("Unknown clean mode: %s", mode)
            return False
        rc = _enc_i32(7, mode_int)          # PbRobotConfig.cleanMode
        raw = _enc_i32(2, PB_VERSION_4_9) + _enc_len(13, rc)
        self._publish(raw)
        if self.data:
            self.data["cleanMode"] = mode
            self.data["robotCleanMode"] = mode_int
        self.async_update_listeners()
        return True

    async def async_set_schedule(self, schedules: list[dict]) -> bool:
        _LOGGER.warning("set_schedule not implemented for MQTT path yet")
        return False

    # ── One-time fetches ─────────────────────────────────────────

    async def async_refresh_device_info(self) -> None:
        try:
            await self.auth.ensure_valid(self._email, self._password)
            self.device_info_data = await self.client.get_device_info(self.thing_name)
        except LymowError as err:
            _LOGGER.warning("Cannot fetch device info for %s: %s", self.thing_name, err)

    async def async_refresh_history(self, count: int = 10) -> list[dict]:
        try:
            await self.auth.ensure_valid(self._email, self._password)
            data = await self.client.get_clean_history(self.thing_name, size=count)
            if isinstance(data, dict):
                self._merge_state({
                    "cleanHistory": data.get("clean_history") or [],
                    "cleanHistorySummary": data.get("clean_summary") or {},
                    "cleanHistoryTotalRecords": data.get("total_records"),
                })
                self.history = data.get("clean_history") or []
            else:
                self.history = data or []
            self.async_set_updated_data(self._state)
            return self.history
        except LymowError as err:
            _LOGGER.warning("History fetch failed: %s", err)
            return []

    async def async_refresh_map(self) -> dict | None:
        try:
            await self._load_backup_map()
            return self._state.get("btMap")
        except LymowError as err:
            _LOGGER.warning("Map fetch failed: %s", err)
            return None

    # ── DataUpdateCoordinator shim ───────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        return self._state