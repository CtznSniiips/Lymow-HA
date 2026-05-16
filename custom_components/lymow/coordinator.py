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
import re

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
    encode_query_map,
    encode_query_path,
    encode_query_schedules,
    encode_query_robot_config,
    decode_pboutput_envelope,
    decode_pbmap,
    parse_query_path,
    parse_zone_catalog,
    parse_schedules,
    encode_start_zones,
    encode_start_schedule_task_full,
    encode_userctrl,
    encode_set_rr_config,
    encode_set_headlights
)
from .state import derive_current_zone, merge_pboutput, robot_gps_from_state
from .state_matrix import lookup as lookup_state_row

_LOGGER = logging.getLogger(__name__)

_REST_POLL_INTERVAL = timedelta(minutes=15)
_REFRESH_INTERVAL   = 90          # seconds — periodic config/net/RTK refresh
_RECONNECT_DELAY    = 5           # seconds — wait before reconnect attempt
_WATCHDOG_TIMEOUT   = 5.0

_PATH_REFRESH_INTERVAL = 45


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
        
        self.hass.async_create_task(self._delayed_query_schedules(3))
        # Robot only responds to robotConfig query after being online for a few seconds
        self.hass.async_create_task(self._delayed_robot_config(4))

    def _fire_refresh_queries(self) -> None:
        """Periodic refresh — keeps IP, signal, RTK and config up to date."""
        for raw in build_refresh_query_packets(client_uuid=self._client_uuid):
            self._publish(raw)
    
    async def _delayed_robot_config(self, delay: int) -> None:
        """Send robot config query with delay — mirrors app behavior (1s + 5s)."""
        await asyncio.sleep(delay)
        self._publish(encode_query_robot_config())
    
    async def _delayed_query_schedules(self, delay: int) -> None:
        """Send robot schedules query with delay — mirrors app behavior (1s + 5s)."""
        await asyncio.sleep(delay)
        self._publish(encode_query_schedules())
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
        return []

    @property
    def state_dict(self) -> dict[str, Any]:
        """Compatibility alias used by helper entities."""
        return self._state
    
    def _normalize_fw_version(self, version: str | None) -> str | None:
        """Remove Lymow date suffix from firmware version.

        Examples:
        v2.1.48_beta_20260512 -> v2.1.48_beta
        v2.1.46_20260510      -> v2.1.46
        """
        if not version:
            return None

        return re.sub(r"_\d{8}$", "", str(version).strip())

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
        btmap = self._dict_or_empty(self._state.get("btMap"))
        for k in ("cutHeight", "cutSpeed", "moveSpeed"):
            if btmap.get(k) is not None and self._state.get(k) is None:
                self._state[k] = btmap[k]


    # ── Inbound MQTT handlers ────────────────────────────────────

    def _dict_or_empty(self, value):
        return value if isinstance(value, dict) else {}

    def _handle_pboutput(self, raw_envelope: bytes) -> None:
        """Decode one MQTT /pboutput packet and merge it into coordinator state.

        `protocol.decode_pboutput_envelope()` now returns a real protobuf
        `PbOutput`. Normal fields are merged in `state.merge_pboutput()`;
        the rich map/catalog branch inside `btMap.queryAck` is parsed
        separately because that inner blob is not fully exposed by the pb2
        schema.
        """
        import time
        self._last_mqtt_ts = time.monotonic()

        try:
            msg = decode_pboutput_envelope(raw_envelope)
        except Exception:
            _LOGGER.exception("Failed to decode PbOutput for %s", self.thing_name)
            return

        if msg is None:
            _LOGGER.debug("Empty pboutput decode for %s", self.thing_name)
            return

        try:
            merge_pboutput(self._state, msg)
        except Exception:
            _LOGGER.exception("Failed to merge PbOutput for %s", self.thing_name)
            return

        # QUERY_MAP rich response. PbOutput is decoded with protobuf, but the
        # nested btMap.queryAck map payload still needs manual wire parsing.
        try:
            if msg.btMap.ByteSize() > 200:
                if getattr(msg.btMap, "queryMap", False):
                    catalog = parse_zone_catalog(msg.btMap)

                    # Sticky catalog: update only when the packet actually carries
                    # zones. QUERY_PATH / small btMap packets must not wipe a good
                    # catalog previously loaded from QUERY_MAP or S3.
                    if catalog.zones:
                        self._state["zone_catalog"] = catalog
                        self._state["btMap"] = catalog.to_btmap_dict()
                        self._state["backupMapDownloadError"] = None

                    if catalog.enu_base_point:
                        self._state["enu_base_point"] = catalog.enu_base_point

                    if catalog.charging_station_loc:
                        self._state["chargingStationLoc"] = catalog.charging_station_loc

                    if catalog.runtime_config:
                        self._state["runTimeConfig"] = catalog.runtime_config
                        for key in ("cutHeight", "cutSpeed", "moveSpeed"):
                            if key in catalog.runtime_config:
                                self._state[key] = catalog.runtime_config[key]

                    _LOGGER.debug(
                        "Parsed Lymow zone catalog for %s: zones=%s channels=%s noGO=%s ebp=%s runtime=%s",
                        self.thing_name,
                        len(catalog.zones),
                        len(catalog.channels),
                        len(catalog.nogo_zones),
                        bool(catalog.enu_base_point),
                        bool(catalog.runtime_config),
                    )
                # QUERY_PATH: traiettoria / coverage / path
                elif getattr(msg.btMap, "queryPath", False):
                    path = parse_query_path(msg.btMap)

                    if path.get("points_count", 0) > 0:
                        segments = path.get("segments") or []

                        # I marker 333/444 vengono già rimossi da parse_query_path().
                        # Ogni segmento valido con almeno 3 punti può essere disegnato come poligono.
                        mowed_polygons = [
                            seg for seg in segments
                            if isinstance(seg, list) and len(seg) >= 3
                        ]

                        self._state["mowed_area_data"] = {
                            "btMap_bytes": path.get("btMap_bytes"),
                            "points_count": path.get("points_count"),
                            "raw_points_count": path.get("raw_points_count"),
                            "marker_count": path.get("marker_count"),
                            "polygon_count": len(mowed_polygons),
                            "segment_count": path.get("segment_count"),
                            "path_length_m": path.get("path_length_m"),
                            "bounds": path.get("bounds"),
                        }

                        self._state["mowed_area_polygons"] = mowed_polygons

                        # Delete old path
                        self._state.pop("planned_path", None)
                        self._state.pop("planned_path_segments", None)
                        self._state.pop("path_data", None)

                        _LOGGER.debug(
                            "Parsed Lymow QUERY_PATH as mowed area for %s: polygons=%s points=%s markers=%s",
                            self.thing_name,
                            len(mowed_polygons),
                            path.get("points_count"),
                            path.get("marker_count"),
                        )
        except Exception:
            _LOGGER.exception("Failed to parse btMap zone catalog for %s", self.thing_name)

        #Parse Schedule
        try:
            if msg.schedule.ByteSize() > 0:
                schedules = parse_schedules(msg.schedule)

                self._state["schedules"] = schedules
                self._state["schedules_data"] = {
                    "task_count": len(schedules),
                    "enabled_count": sum(1 for s in schedules if s.enabled),
                    "disabled_count": sum(1 for s in schedules if not s.enabled),
                    "tasks": [s.to_dict() for s in schedules],
                }
        except Exception:
            _LOGGER.exception("Failed to parse bpSchedule for %s", self.thing_name)

        self._derive_state()

        _LOGGER.debug(
            "State update %s: workStatus=%s battery=%s catalog=%s",
            self.thing_name,
            self._state.get("workStatus"),
            self._state.get("battery"),
            bool(self._state.get("zone_catalog")),
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
                    if self.work_status in (2, 8, 9):  # mowing, resume, zone partition
                        self._publish(encode_query_path())
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
                    self._normalize_fw_version(update_info.get("latestVersion"))
                )
                note = (
                    update_info.get("releaseNote")
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

    async def _preflight_query_map(self, timeout: float = 3.0) -> None:
        """Ask for a fresh map/state snapshot before user commands.

        The mower often emits a useful state echo after QUERY_MAP. The command
        methods do not fail if the preflight times out; they just proceed with
        the best state currently available.
        """
        if self.mqtt and self.mqtt.is_connected:
            self._publish(encode_query_map())
            await self._wait_state_update(timeout=timeout)

    def _state_row(self):
        return lookup_state_row(
            work_status=self._state.get("workStatus"),
            robot_status=self._state.get("robotStatus"),
            is_recharging=self._state.get("isRecharging"),
        )

    # ── Commands ─────────────────────────────────────────────────

    async def async_start_mow(self, zone_ids: list[str] | None = None) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        await self._preflight_query_map()
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
        await self._preflight_query_map()
        row = self._state_row()
        ctrl = row.pause or (USER_CTRL_PAUSE_DOCK if self.work_status in (WORK_STATUS_DOCKING, WORK_STATUS_PAUSE_DOCKING) else USER_CTRL_PAUSE)
        ok   = self._publish(encode_userctrl(ctrl))
        await self._wait_state_update()
        return ok

    async def async_resume(self) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        await self._preflight_query_map()
        ctrl = USER_CTRL_RESUME_DOCK if self.work_status == WORK_STATUS_PAUSE_DOCKING else USER_CTRL_RESUME
        ok   = self._publish(encode_userctrl(ctrl))
        await self._wait_state_update()
        return ok

    async def async_dock(self) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        await self._preflight_query_map()
        row = self._state_row()
        ok = self._publish(encode_userctrl(row.dock or USER_CTRL_RECHARGE_DOCK))
        await self._wait_state_update()
        return ok

    async def async_dock_cancel_task(self) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        await self._preflight_query_map()
        ok = self._publish(encode_userctrl(USER_CTRL_DOCK))
        await self._wait_state_update()
        return ok

    async def async_stop(self) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        await self._preflight_query_map()
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

        Per live wire captures, cleanMode sits at field 7 of PbRobotConfig
        (PbInput field 13). See encode_set_clean_mode() for encoding details.
        """
        from .protocol import encode_set_clean_mode, CLEAN_MODE_STR
        mode_int = CLEAN_MODE_STR.get(mode)
        if mode_int is None:
            _LOGGER.warning("Unknown clean mode: %s", mode)
            return False
        self._publish(encode_set_clean_mode(mode_int))
        if self.data:
            self.data["cleanMode"] = mode
            self.data["robotCleanMode"] = mode_int
        self.async_update_listeners()
        return True

    async def async_set_schedule(self, schedules: list[dict]) -> bool:
        _LOGGER.warning("set_schedule not implemented for MQTT path yet")
        return False
    
    async def async_start_schedule_task(self, schedule_id: int) -> bool:
        """Start one decoded schedule manually."""
        await self.auth.ensure_valid(self._email, self._password)

        tasks = ((self._state.get("schedules_data") or {}).get("tasks") or [])
        task = next((t for t in tasks if int(t.get("id", -1)) == int(schedule_id)), None)

        if not task:
            _LOGGER.warning("Schedule task %s not found for %s", schedule_id, self.thing_name)
            return False

        zone_hash_ids = task.get("zoneHashIds") or []
        if not zone_hash_ids:
            _LOGGER.warning("Schedule task %s has no zones", schedule_id)
            return False

        # Stato fresco prima del comando
        self._publish(encode_query_map())
        await self._wait_state_update(timeout=3.0)

        raw = encode_start_schedule_task_full(task)

        # opzionale: pulisci vecchia area tagliata
        self._state.pop("mowed_area_polygons", None)
        self._state.pop("mowed_area_data", None)

        ok = self._publish(raw)
        await self._wait_state_update()
        return ok
    
    async def async_set_headlights(self, enabled: bool) -> bool:
        """Turn headlights on or off."""
        await self.auth.ensure_valid(self._email, self._password)

        raw = encode_set_headlights(enabled)

        ok = self._publish(raw)
        await self._wait_state_update()

        # Ask for robot config again, so camLedStatus updates quickly.
        self._publish(encode_query_robot_config())
        await self._wait_state_update(timeout=3.0)

        return ok
    
    async def _send_rr_update(
        self,
        *,
        enable_rr: bool | None = None,
        recharge_bat: int | None = None,
        resume_bat: int | None = None,
    ) -> bool:
        """Update rrConfig while preserving existing values."""

        await self.auth.ensure_valid(self._email, self._password)

        d = self._state or {}

        current_enable = d.get("rrEnabled")
        current_recharge = d.get("rrRechargeBat")
        current_resume = d.get("rrResumeBat")

        # Default sicuri se il robotConfig non è ancora arrivato
        if current_enable is None:
            current_enable = True
        if current_recharge is None:
            current_recharge = 10
        if current_resume is None:
            current_resume = 98

        # Orari RR già flattenati nello state.py, se presenti
        rr_start = d.get("rrResumePeriodStart") or {}
        rr_end = d.get("rrResumePeriodEnd") or {}

        start_h = int(rr_start.get("hour", 0)) if isinstance(rr_start, dict) else 0
        start_m = int(rr_start.get("minute", 0)) if isinstance(rr_start, dict) else 0
        end_h = int(rr_end.get("hour", 0)) if isinstance(rr_end, dict) else 0
        end_m = int(rr_end.get("minute", 0)) if isinstance(rr_end, dict) else 0

        raw = encode_set_rr_config(
            enable_rr=bool(current_enable if enable_rr is None else enable_rr),
            recharge_bat=int(current_recharge if recharge_bat is None else recharge_bat),
            resume_bat=int(current_resume if resume_bat is None else resume_bat),
            period_start_hour=start_h,
            period_start_minute=start_m,
            period_end_hour=end_h,
            period_end_minute=end_m,
        )

        ok = self._publish(raw)
        await self._wait_state_update()
        return ok


    async def async_set_auto_recharge(self, enabled: bool) -> bool:
        """Enable/disable auto recharge."""
        return await self._send_rr_update(enable_rr=enabled)


    async def cmd_set_auto_recharge(self, enabled: bool) -> bool:
        """Alias used by switch entities."""
        return await self.async_set_auto_recharge(enabled)


    async def async_set_recharge_threshold(self, value: int) -> bool:
        """Set battery percentage where mower should go recharge."""
        value = max(1, min(100, int(value)))
        return await self._send_rr_update(recharge_bat=value)


    async def cmd_set_recharge_threshold(self, value: int) -> bool:
        """Alias used by number entities."""
        return await self.async_set_recharge_threshold(value)


    async def async_set_resume_threshold(self, value: int) -> bool:
        """Set battery percentage where mower should resume mowing."""
        value = max(1, min(100, int(value)))
        return await self._send_rr_update(resume_bat=value)


    async def cmd_set_resume_threshold(self, value: int) -> bool:
        """Alias used by number entities."""
        return await self.async_set_resume_threshold(value)
    
    async def async_set_rr_start_time(self, hour: int, minute: int) -> bool:
        """Set RR resume period start time."""
        await self.auth.ensure_valid(self._email, self._password)

        d = self._state or {}

        current_enable = d.get("rrEnabled")
        current_recharge = d.get("rrRechargeBat")
        current_resume = d.get("rrResumeBat")

        if current_enable is None:
            current_enable = True
        if current_recharge is None:
            current_recharge = 10
        if current_resume is None:
            current_resume = 98

        rr_end = d.get("rrResumePeriodEnd") or {}
        end_h = int(rr_end.get("hour", 0)) if isinstance(rr_end, dict) else 0
        end_m = int(rr_end.get("minute", 0)) if isinstance(rr_end, dict) else 0

        raw = encode_set_rr_config(
            enable_rr=bool(current_enable),
            recharge_bat=int(current_recharge),
            resume_bat=int(current_resume),
            period_start_hour=max(0, min(23, int(hour))),
            period_start_minute=max(0, min(59, int(minute))),
            period_end_hour=end_h,
            period_end_minute=end_m,
        )

        ok = self._publish(raw)
        await self._wait_state_update()
        return ok


    async def async_set_rr_end_time(self, hour: int, minute: int) -> bool:
        """Set RR resume period end time."""
        await self.auth.ensure_valid(self._email, self._password)

        d = self._state or {}

        current_enable = d.get("rrEnabled")
        current_recharge = d.get("rrRechargeBat")
        current_resume = d.get("rrResumeBat")

        if current_enable is None:
            current_enable = True
        if current_recharge is None:
            current_recharge = 10
        if current_resume is None:
            current_resume = 98

        rr_start = d.get("rrResumePeriodStart") or {}
        start_h = int(rr_start.get("hour", 0)) if isinstance(rr_start, dict) else 0
        start_m = int(rr_start.get("minute", 0)) if isinstance(rr_start, dict) else 0

        raw = encode_set_rr_config(
            enable_rr=bool(current_enable),
            recharge_bat=int(current_recharge),
            resume_bat=int(current_resume),
            period_start_hour=start_h,
            period_start_minute=start_m,
            period_end_hour=max(0, min(23, int(hour))),
            period_end_minute=max(0, min(59, int(minute))),
        )

        ok = self._publish(raw)
        await self._wait_state_update()
        return ok

    # ── One-time fetches ─────────────────────────────────────────

    async def async_refresh_device_info(self) -> None:
        try:
            await self.auth.ensure_valid(self._email, self._password)
            self.device_info_data = await self.client.get_device_info(self.thing_name)
        except LymowError as err:
            _LOGGER.warning("Cannot fetch device info for %s: %s", self.thing_name, err)
    
    async def async_refresh_schedules(self) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        ok = self._publish(encode_query_schedules())
        await self._wait_state_update()
        return ok

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

    # ── DataUpdateCoordinator shim ───────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        return self._state