"""DataUpdateCoordinator for Lymow — MQTT push-driven.

No periodic shadow polling. State arrives via MQTT /pboutput broadcasts.
Commands are published to /pbinput as protobuf messages.

Startup sequence:
  1. REST device-info (for IP, firmware version)
  2. MQTT connect + subscribe
  3. QUERY_MAP (with btMap.queryMap=True) — triggers full state broadcast
  4. QUERY_SCHEDULES — triggers schedule broadcast
  5. Listen for push updates indefinitely

REST online poll runs every 15 minutes to detect prolonged offline states.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CognitoAuth, LymowClient, LymowError
from .const import (
    DEVICE_STATE_OFFLINE,
    DOMAIN,
    F_DEVICE_STATE,
    WORK_STATUS_MOWING,
    WORK_STATUS_OFFLINE,
    WORK_STATUS_DOCKING,
    WORK_STATUS_PAUSE_DOCKING,
)
from .mqtt import MqttClient
from .protocol import (
    USER_CTRL_CLEAN,
    USER_CTRL_DOCK,
    USER_CTRL_FORCE_REINIT,
    USER_CTRL_PAUSE,
    USER_CTRL_PAUSE_DOCK,
    USER_CTRL_QUERY_MAP,
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

_REST_POLL_INTERVAL  = timedelta(minutes=15)
_WATCHDOG_TIMEOUT    = 5.0  # seconds to wait for state confirmation after command


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
        # update_interval=None → push-only, never calls _async_update_data on timer
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{thing_name}",
            update_interval=None,
        )
        self.auth       = auth
        self.client     = client
        self.thing_name = thing_name
        self._region    = region
        self._email     = email
        self._password  = password

        # State dict — single source of truth for all entities
        self._state: dict[str, Any] = {}

        # Static info fetched once after setup
        self.device_info_data: dict = {}
        self.history: list[dict]    = []

        # Online tracking
        self._rest_online: bool       = False
        self._last_mqtt_ts: float     = 0.0

        # Previous workStatus for detecting transitions (e.g. WAITING→MOWING)
        self._prev_work_status: int | None = None

        # MQTT client (created in async_setup)
        self.mqtt: MqttClient | None = None

        # Background task handle
        self._rest_poll_task: asyncio.Task | None = None

        # Event set whenever a new MQTT message arrives (for command watchdog)
        self._state_event = asyncio.Event()

    # ── Setup / teardown ────────────────────────────────────────

    async def async_setup(self) -> None:
        """Connect MQTT and fire startup queries."""
        await self.auth.ensure_valid(self._email, self._password)

        # Initial REST device-info (IP for camera, online flag)
        await self._do_rest_poll()

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

        # Fire startup queries — responses arrive as MQTT pushes
        self._publish(encode_query_map())
        self._publish(encode_userctrl(USER_CTRL_QUERY_SCHEDULES))

        # Start background REST poll
        self._rest_poll_task = self.hass.async_create_task(self._rest_poll_loop())

    async def async_shutdown(self) -> None:
        """Disconnect MQTT and cancel background tasks."""
        if self._rest_poll_task:
            self._rest_poll_task.cancel()
            try:
                await self._rest_poll_task
            except asyncio.CancelledError:
                pass
        if self.mqtt:
            await self.mqtt.disconnect()
            self.mqtt = None

    # ── Properties ──────────────────────────────────────────────

    @property
    def state_dict(self) -> dict[str, Any]:
        return self._state

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
    def data(self) -> dict[str, Any]:
        return self._state

    # ── Inbound MQTT handlers ────────────────────────────────────

    def _handle_pboutput(self, raw_envelope: bytes) -> None:
        """Called from asyncio loop (bridged from paho thread)."""
        import time
        self._last_mqtt_ts = time.monotonic()

        new_state = decode_pboutput_envelope(raw_envelope)
        if not new_state:
            _LOGGER.debug("Empty pboutput decode for %s", self.thing_name)
            return

        # Merge into existing state (MQTT sends partial updates)
        self._state.update(new_state)

        # Track workStatus transitions
        new_ws = new_state.get("workStatus")
        if new_ws is not None:
            self._prev_work_status = new_ws

        _LOGGER.debug("State update %s: workStatus=%s battery=%s",
                      self.thing_name,
                      self._state.get("workStatus"),
                      self._state.get("battery"))

        self._state_event.set()
        self.async_set_updated_data(self._state)

    def _handle_notify_app(self, payload: dict) -> None:
        """JSON {deviceThingName, robotState: online|offline, ...}."""
        rs = payload.get("robotState")
        if rs == "online":
            self._rest_online = True
            self._state["deviceState"] = "online"
            self._state["isOnline"]    = True
        elif rs == "offline":
            self._rest_online = False
            self._state["deviceState"] = "offline"
            self._state["isOnline"]    = False
        self.async_set_updated_data(self._state)

    def _handle_disconnect(self) -> None:
        """Called from asyncio loop when paho disconnects."""
        _LOGGER.warning("MQTT disconnected for %s — paho will auto-reconnect", self.thing_name)
        # paho handles reconnect automatically; nothing to do here.
        # A future improvement could refresh creds + force reconnect on persistent failure.

    # ── REST poll ────────────────────────────────────────────────

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
                ip = info.get("ipAddress") or info.get("ip_address")
                if ip:
                    self._state["rest_ip_address"] = ip
            else:
                self._rest_online = False
        except Exception:
            _LOGGER.debug("REST poll error for %s", self.thing_name, exc_info=True)
        self.async_set_updated_data(self._state)

    # ── Publish helpers ──────────────────────────────────────────

    def _publish(self, raw: bytes) -> bool:
        if not self.mqtt:
            return False
        return self.mqtt.publish(raw)

    async def _wait_state_update(self, timeout: float = _WATCHDOG_TIMEOUT) -> bool:
        """Wait for any new MQTT state message within timeout seconds."""
        self._state_event.clear()
        try:
            await asyncio.wait_for(self._state_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    # ── Command methods (called by entities) ─────────────────────

    async def async_start_mow(self, zone_ids: list[str] | None = None) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        if zone_ids:
            raw = encode_start_zones(zone_ids)
        else:
            raw = encode_userctrl(USER_CTRL_CLEAN)
        ok = self._publish(raw)
        await self._wait_state_update()
        return ok

    async def async_pause(self) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        # Pick variant based on current state
        ws = self.work_status
        if ws in (WORK_STATUS_DOCKING, WORK_STATUS_PAUSE_DOCKING):
            ctrl = USER_CTRL_PAUSE_DOCK
        else:
            ctrl = USER_CTRL_PAUSE
        ok = self._publish(encode_userctrl(ctrl))
        await self._wait_state_update()
        return ok

    async def async_resume(self) -> bool:
        await self.auth.ensure_valid(self._email, self._password)
        ws = self.work_status
        if ws == WORK_STATUS_PAUSE_DOCKING:
            ctrl = USER_CTRL_RESUME_DOCK
        else:
            ctrl = USER_CTRL_RESUME
        ok = self._publish(encode_userctrl(ctrl))
        await self._wait_state_update()
        return ok

    async def async_dock(self) -> bool:
        """Dock and keep task progress (safer default)."""
        await self.auth.ensure_valid(self._email, self._password)
        ok = self._publish(encode_userctrl(USER_CTRL_RECHARGE_DOCK))
        await self._wait_state_update()
        return ok

    async def async_dock_cancel_task(self) -> bool:
        """Dock and abandon task."""
        await self.auth.ensure_valid(self._email, self._password)
        ok = self._publish(encode_userctrl(USER_CTRL_DOCK))
        await self._wait_state_update()
        return ok

    async def async_stop(self) -> bool:
        """Stop in place and reset to WAITING."""
        await self.auth.ensure_valid(self._email, self._password)
        ok = self._publish(encode_userctrl(USER_CTRL_FORCE_REINIT))
        await self._wait_state_update()
        return ok

    async def async_set_blade_height(self, height_mm: int) -> bool:
        """Write blade height to shadow (persistent config)."""
        await self.auth.ensure_valid(self._email, self._password)
        return await self.client.cmd_set_blade_height(self.thing_name, height_mm)

    async def async_set_clean_mode(self, mode: str) -> bool:
        """Write clean mode to shadow (persistent config)."""
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

    # ── Compatibility shim: _async_update_data ───────────────────
    # DataUpdateCoordinator requires this, but we never call it on a timer.
    # Returning the current state is sufficient.

    async def _async_update_data(self) -> dict[str, Any]:
        return self._state
