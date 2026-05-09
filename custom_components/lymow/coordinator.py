"""DataUpdateCoordinator for Lymow — MQTT push-driven.

State arrives via MQTT /pboutput broadcasts.
Commands are published to /pbinput as protobuf messages.

Startup + periodic refresh:
  On connect:
    QUERY_MAP          → full map + zone list (btMap)
    QUERY_SCHEDULES    → schedules
    QUERY_ROBOT_CONFIG → firmware version, IP, blade height, clean mode
    QUERY_NET_DETAIL   → WiFi/LTE info
    QUERY_RTK_L1       → RTK status

  Every _REFRESH_INTERVAL (default 90s):
    QUERY_ROBOT_CONFIG + QUERY_NET_DETAIL + QUERY_RTK_L1
    (ensures IP address and signal info stay current without the app open)

  On MQTT disconnect:
    Refresh AWS credentials (they expire after ~1h causing the disconnect)
    Re-create paho connection with a new presigned URL
    Re-fire startup queries

REST poll every 15 min: device online/offline fallback.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
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
    USER_CTRL_QUERY_NET_DETAIL,
    USER_CTRL_QUERY_ROBOT_CFG,
    USER_CTRL_QUERY_RTK_L1,
    USER_CTRL_QUERY_SCHEDULES,
    USER_CTRL_RECHARGE_DOCK,
    USER_CTRL_RESUME,
    USER_CTRL_RESUME_DOCK,
    decode_pboutput_envelope,
    encode_query_map,
    encode_start_zones,
    encode_userctrl,
)

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
        """Authenticate, connect MQTT, fire startup queries."""
        self._shutting_down = False
        await self.auth.ensure_valid(self._email, self._password)
        await self._do_rest_poll()
        await self._connect_mqtt()

        self._rest_poll_task = self.hass.async_create_task(self._rest_poll_loop())
        self._refresh_task   = self.hass.async_create_task(self._refresh_loop())

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
            host=self.client._iot_host,
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
        self._publish(encode_query_map())
        self._publish(encode_userctrl(USER_CTRL_QUERY_SCHEDULES))
        self._publish(encode_userctrl(USER_CTRL_QUERY_ROBOT_CFG))
        self._publish(encode_userctrl(USER_CTRL_QUERY_NET_DETAIL))
        self._publish(encode_userctrl(USER_CTRL_QUERY_RTK_L1))

    def _fire_refresh_queries(self) -> None:
        """Periodic refresh — keeps IP, signal, RTK and config up to date."""
        self._publish(encode_userctrl(USER_CTRL_QUERY_ROBOT_CFG))
        self._publish(encode_userctrl(USER_CTRL_QUERY_NET_DETAIL))
        self._publish(encode_userctrl(USER_CTRL_QUERY_RTK_L1))

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

    # ── Inbound MQTT handlers ────────────────────────────────────

    def _handle_pboutput(self, raw_envelope: bytes) -> None:
        import time
        self._last_mqtt_ts = time.monotonic()

        new_state = decode_pboutput_envelope(raw_envelope)
        if not new_state:
            _LOGGER.debug("Empty pboutput decode for %s", self.thing_name)
            return

        # Merge — never lose previously received data
        for k, v in new_state.items():
            if isinstance(v, dict) and isinstance(self._state.get(k), dict):
                self._state[k].update(v)
            else:
                self._state[k] = v

        if (ws := new_state.get("workStatus")) is not None:
            self._prev_work_status = ws

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
            self._reconnect_task = self.hass.async_create_task(
                self._reconnect_with_fresh_creds()
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

    async def _do_rest_poll(self) -> None:
        try:
            await self.auth.ensure_valid(self._email, self._password)
            info = await self.client.get_device_info(self.thing_name)
            if info:
                self.device_info_data = info
                ds = info.get("deviceState") or info.get("device_state") or "offline"
                self._rest_online = ds == "online"
                if ip := info.get("ipAddress") or info.get("ip_address"):
                    self._state["rest_ip_address"] = ip
            else:
                self._rest_online = False
        except Exception:
            _LOGGER.debug("REST poll error for %s", self.thing_name, exc_info=True)
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

    # ── Commands ─────────────────────────────────────────────────

    async def async_start_mow(self, zone_ids: list[str] | None = None) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        raw = encode_start_zones(zone_ids) if zone_ids else encode_userctrl(USER_CTRL_CLEAN)
        ok  = self._publish(raw)
        await self._wait_state_update()
        return ok

    async def async_pause(self) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        ws   = self.work_status
        ctrl = USER_CTRL_PAUSE_DOCK if ws in (WORK_STATUS_DOCKING, WORK_STATUS_PAUSE_DOCKING) else USER_CTRL_PAUSE
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
        ok = self._publish(encode_userctrl(USER_CTRL_RECHARGE_DOCK))
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

    async def async_set_blade_height(self, height_mm: int) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        return await self.client.cmd_set_blade_height(self.thing_name, height_mm)

    async def async_set_clean_mode(self, mode: str) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        return await self.client.cmd_set_clean_mode(self.thing_name, mode)

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
            self.history = await self.client.get_clean_history(self.thing_name, size=count)
            return self.history
        except LymowError as err:
            _LOGGER.warning("History fetch failed: %s", err)
            return []

    async def async_refresh_map(self) -> dict | None:
        try:
            await self.auth.ensure_valid(self._email, self._password)
            return await self.client.get_backup_map(self.thing_name)
        except LymowError as err:
            _LOGGER.warning("Map fetch failed: %s", err)
            return None

    # ── DataUpdateCoordinator shim ───────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        return self._state
