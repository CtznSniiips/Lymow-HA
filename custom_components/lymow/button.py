"""Lymow button platform.

Command buttons call the coordinator methods instead of publishing protobuf
payloads directly, so command preflight/watchdog logic stays in one place.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from datetime import datetime, timezone
import re

from homeassistant.util import dt as dt_util

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.const import EntityCategory

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import (
    DOMAIN,
    MOWING_STATUSES,
    WORK_STATUS_EMERGENCY_STOP,
    WORK_STATUS_ERROR,
    WORK_STATUS_ESCAPING,
    WORK_STATUS_PAUSE,
    WORK_STATUS_UPDATING,
)
from .coordinator import LymowCoordinator
from .entity_base import LymowEntity
from .protocol import encode_query_map, encode_query_robot_config, encode_query_schedules

_LOGGER = logging.getLogger(__name__)

# Dock (RECHARGE_DOCK) only acts with a live, resumable task to come home to.
DOCKABLE_STATUSES = MOWING_STATUSES | {WORK_STATUS_PAUSE, WORK_STATUS_ESCAPING}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: LymowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            LymowStartButton(coord),
            LymowPauseButton(coord),
            LymowResumeButton(coord),
            LymowDockButton(coord),
            LymowCancelTaskButton(coord),
            LymowDockCancelButton(coord),
            LymowClearErrorButton(coord),
            LymowOtaUpdateButton(coord),
            LymowAbortOtaButton(coord),

            # Remote control buttons
            LymowRemoteButton(
                coord,
                key="remote_forward",
                name="Remote forward",
                icon="mdi:arrow-up-bold",
                action="async_remote_forward",
            ),
            LymowRemoteButton(
                coord,
                key="remote_backward",
                name="Remote backward",
                icon="mdi:arrow-down-bold",
                action="async_remote_backward",
            ),
            LymowRemoteButton(
                coord,
                key="remote_left",
                name="Remote left",
                icon="mdi:arrow-left-bold",
                action="async_remote_left",
            ),
            LymowRemoteButton(
                coord,
                key="remote_right",
                name="Remote right",
                icon="mdi:arrow-right-bold",
                action="async_remote_right",
            ),
            LymowRemoteButton(
                coord,
                key="remote_stop",
                name="Remote stop",
                icon="mdi:stop-circle",
                action="async_remote_stop",
            ),

            LymowRefreshMapButton(coord),
            LymowRefreshRobotConfigButton(coord),
            LymowRefreshSchedulesButton(coord),
            LymowRefreshDeviceInfoButton(coord),
            LymowRefreshHistoryButton(coord),
        ],
        update_before_add=False,
    )

    added_schedule_ids: set[int] = set()

    def _schedule_tasks() -> list[dict[str, Any]]:
        data = coord.data or {}
        schedules_data = data.get("schedules_data") or {}
        tasks = schedules_data.get("tasks") or []
        return [t for t in tasks if isinstance(t, dict) and t.get("id") is not None]

    @callback
    def _maybe_add_schedule_buttons() -> None:
        new_entities: list[ButtonEntity] = []

        for task in _schedule_tasks():
            try:
                schedule_id = int(task["id"])
            except (TypeError, ValueError):
                continue

            if schedule_id in added_schedule_ids:
                continue

            added_schedule_ids.add(schedule_id)
            new_entities.append(LymowScheduleStartButton(coord, schedule_id))

        if new_entities:
            async_add_entities(new_entities)

    # Prova subito, se le schedule sono già presenti
    _maybe_add_schedule_buttons()

    # Poi crea i bottoni quando arrivano via MQTT
    entry.async_on_unload(coord.async_add_listener(_maybe_add_schedule_buttons))

class LymowRemoteButton(LymowEntity, ButtonEntity):
    def __init__(
        self,
        coordinator: LymowCoordinator,
        *,
        key: str,
        name: str,
        icon: str,
        action: str,
    ) -> None:
        super().__init__(coordinator, key)

        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._action = action

    async def async_press(self) -> None:
        method = getattr(self.coordinator, self._action, None)

        if method is None:
            raise HomeAssistantError(f"Remote action not found: {self._action}")

        ok = await method()

        if ok is False:
            raise HomeAssistantError(f"Remote action failed: {self._action}")

class _LymowButton(LymowEntity, ButtonEntity):
    """Base for all Lymow command buttons."""

    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: LymowCoordinator, key: str) -> None:
        super().__init__(coordinator, key)


class LymowStartButton(_LymowButton):
    """Start or resume mowing using the coordinator state matrix."""

    _attr_name = "Start Mowing"
    _attr_icon = "mdi:play"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_start")

    async def async_press(self) -> None:
        _LOGGER.debug("Lymow Start button pressed")
        await self.coordinator.async_start_mow()


class LymowPauseButton(_LymowButton):
    """Pause mowing or docking."""

    _attr_name = "Pause"
    _attr_icon = "mdi:pause"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_pause")

    async def async_press(self) -> None:
        _LOGGER.debug("Lymow Pause button pressed")
        await self.coordinator.async_pause()


class LymowResumeButton(_LymowButton):
    """Resume mowing or resume docking from pause."""

    _attr_name = "Resume"
    _attr_icon = "mdi:play-pause"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_resume")

    async def async_press(self) -> None:
        _LOGGER.debug("Lymow Resume button pressed")
        await self.coordinator.async_resume()


class LymowDockButton(_LymowButton):
    """Return to dock and keep task progress so the mow can resume (RECHARGE_DOCK).

    Only available while there's a live, resumable task — an active mow or a
    pause mid-mow. From idle the firmware has nothing to resume and ignores the
    command, so the button is gray then; use "Dock & Cancel" to send it home
    from any other state."""

    _attr_name = "Dock"
    _attr_icon = "mdi:home-import-outline"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_dock")

    @property
    def available(self) -> bool:
        d = self.coordinator.data or {}
        return super().available and (
            d.get("workStatus") in DOCKABLE_STATUSES
            or d.get("robotStatus") in DOCKABLE_STATUSES
        )

    async def async_press(self) -> None:
        _LOGGER.debug("Lymow Dock button pressed")
        await self.coordinator.async_dock()


class LymowCancelTaskButton(_LymowButton):
    """Stop in place and cancel/reset the current task."""

    _attr_name = "Cancel Task"
    _attr_icon = "mdi:cancel"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_cancel_task")

    async def async_press(self) -> None:
        _LOGGER.debug("Lymow Cancel Task button pressed")
        await self.coordinator.async_stop()


class LymowDockCancelButton(_LymowButton):
    """Return to dock and abandon current task progress."""

    _attr_name = "Dock & Cancel"
    _attr_icon = "mdi:home-remove-outline"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_dock_cancel")

    async def async_press(self) -> None:
        _LOGGER.debug("Lymow Dock & Cancel button pressed")
        await self.coordinator.async_dock_cancel_task()


class _LymowRawQueryButton(_LymowButton):
    """Diagnostic button that publishes a single query packet."""

    _attr_entity_registry_enabled_default = False
    _packet_name: str = ""

    def _publish_packet(self, raw: bytes) -> None:
        if not self.coordinator._publish(raw):
            _LOGGER.warning("Failed to publish %s query", self._packet_name)


class LymowRefreshMapButton(_LymowRawQueryButton):
    """Ask the robot for a fresh live QUERY_MAP response."""

    _attr_name = "Refresh Map"
    _attr_icon = "mdi:map-sync"
    _packet_name = "QUERY_MAP"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_refresh_map")

    async def async_press(self) -> None:
        self._publish_packet(encode_query_map())


class LymowRefreshRobotConfigButton(_LymowRawQueryButton):
    """Ask the robot for its robotConfig/rrConfig state."""

    _attr_name = "Refresh Robot Config"
    _attr_icon = "mdi:cog-refresh"
    _packet_name = "QUERY_ROBOT_CONFIG"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_refresh_robot_config")

    async def async_press(self) -> None:
        self._publish_packet(encode_query_robot_config())


class LymowRefreshSchedulesButton(_LymowRawQueryButton):
    """Ask the robot for its schedule list."""

    _attr_name = "Refresh Schedules"
    _attr_icon = "mdi:calendar-sync"
    _packet_name = "QUERY_SCHEDULES"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_refresh_schedules")

    async def async_press(self) -> None:
        self._publish_packet(encode_query_schedules())


class LymowRefreshDeviceInfoButton(_LymowButton):
    """Refresh REST device metadata."""

    _attr_name = "Refresh Device Info"
    _attr_icon = "mdi:information-outline"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_refresh_device_info")

    async def async_press(self) -> None:
        await self.coordinator.async_refresh_device_info()


class LymowRefreshHistoryButton(_LymowButton):
    """Refresh REST mowing history summary."""

    _attr_name = "Refresh History"
    _attr_icon = "mdi:history"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_refresh_history")

    async def async_press(self) -> None:
        await self.coordinator.async_refresh_history()

class LymowScheduleStartButton(_LymowButton):
    """Start a decoded schedule manually."""

    _attr_icon = "mdi:calendar-play"

    def __init__(self, coordinator: LymowCoordinator, schedule_id: int) -> None:
        self._schedule_id = int(schedule_id)
        super().__init__(coordinator, f"schedule_{self._schedule_id}_start")

    def _schedule(self) -> dict[str, Any] | None:
        data = self.coordinator.data or {}
        schedules_data = data.get("schedules_data") or {}
        tasks = schedules_data.get("tasks") or []

        for task in tasks:
            try:
                if int(task.get("id", -1)) == self._schedule_id:
                    return task
            except (TypeError, ValueError):
                continue

        return None

    @property
    def name(self) -> str:
        task = self._schedule()
        if not task:
            return f"Start Schedule {self._schedule_id}"

        days = ", ".join(task.get("dayNames") or [])
        time = self._local_time_from_task(task)

        zone_names = self._zone_display_names(task)
        readable_zone_names = [
            z for z in zone_names
            if z and not self._is_hash_like(z)
        ]

        if readable_zone_names:
            zones_label = ", ".join(readable_zone_names[:3])
            if len(readable_zone_names) > 3:
                zones_label += f" +{len(readable_zone_names) - 3}"
        else:
            zones = task.get("zoneHashIds") or []
            zones_label = f"{len(zones)} zones"

        if days:
            return f"Start Schedule {days} {time} ({zones_label})"

        return f"Start Schedule {time} ({zones_label})"

    @property
    def available(self) -> bool:
        return super().available and self._schedule() is not None

    async def async_press(self) -> None:
        task = self._schedule()
        if not task:
            raise HomeAssistantError(f"Schedule {self._schedule_id} not found")

        zone_hash_ids = task.get("zoneHashIds") or []
        if not zone_hash_ids:
            raise HomeAssistantError(f"Schedule {self._schedule_id} has no zones")

        ok = await self.coordinator.async_start_schedule_task(self._schedule_id)
        if not ok:
            raise HomeAssistantError(f"Failed to start schedule {self._schedule_id}")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        task = self._schedule()
        if not task:
            return {
                "schedule_id": self._schedule_id,
                "available": False,
            }

        zone_hash_ids = task.get("zoneHashIds") or []
        zone_display_names = self._zone_display_names(task)

        return {
            "schedule_id": self._schedule_id,
            "enabled": task.get("enabled"),

            # Original robot schedule time.
            "time_utc": task.get("time"),
            "hour_utc": task.get("hour"),
            "minute_utc": task.get("minute"),

            # Schedule time converted to the Home Assistant timezone.
            "time_local": self._local_time_from_task(task),
            "timezone": self.coordinator.hass.config.time_zone,

            "days_of_week": task.get("daysOfWeek") or [],
            "day_names": task.get("dayNames") or [],
            "is_repeated": task.get("isRepeated"),
            "is_disabled": task.get("isDisabled"),
            "is_angle_offset": task.get("isAngleOffset"),
            "mow_angle": task.get("mowAngle"),

            "zone_hash_ids": zone_hash_ids,
            "zone_names": zone_display_names,
            "zones": task.get("zones") or [],

            "config": task.get("config") or [],
            "config_count": task.get("config_count"),
        }
    
    def _local_time_from_task(self, task: dict[str, Any]) -> str:
        """Return the schedule time converted from UTC to the Home Assistant timezone."""

        try:
            hour = int(task.get("hour", 0))
            minute = int(task.get("minute", 0))
        except (TypeError, ValueError):
            return task.get("time") or "00:00"

        # The task only contains hour/minute, not a full date.
        # Use today's UTC date so Home Assistant can apply the configured
        # timezone correctly, including the current DST offset.
        now_utc = dt_util.utcnow()
        utc_dt = datetime(
            now_utc.year,
            now_utc.month,
            now_utc.day,
            hour,
            minute,
            tzinfo=timezone.utc,
        )

        local_dt = dt_util.as_local(utc_dt)
        return local_dt.strftime("%H:%M")


    def _is_hash_like(self, value: Any) -> bool:
        """Return True if the value looks like an internal zone hash id."""

        if not isinstance(value, str):
            return False

        value = value.strip()
        if not value:
            return False

        # Typical zone hashes look like jNHSquRg, Ywl0HqOo, etc.
        return bool(re.fullmatch(r"[A-Za-z0-9_-]{6,}", value))


    def _zone_name_map(self) -> dict[str, str]:
        """Build a hash_id -> readable zone name map from coordinator data."""

        data = self.coordinator.data or {}

        # Try multiple possible locations because the zone catalog may be stored
        # in different coordinator keys depending on the integration version.
        candidates = []

        for key in (
            "zone_catalog",
            "zones",
            "map_zones",
        ):
            value = data.get(key)
            if isinstance(value, list):
                candidates.extend(value)

        map_data = data.get("map_data") or {}
        if isinstance(map_data, dict):
            for key in (
                "zone_catalog",
                "zones",
                "map_zones",
            ):
                value = map_data.get(key)
                if isinstance(value, list):
                    candidates.extend(value)

        result: dict[str, str] = {}

        for zone in candidates:
            if not isinstance(zone, dict):
                continue

            hash_id = (
                zone.get("hashId")
                or zone.get("hash_id")
                or zone.get("id")
                or zone.get("zoneHashId")
            )

            name = (
                zone.get("name")
                or zone.get("zoneName")
                or zone.get("label")
            )

            if not hash_id or not name:
                continue

            hash_id = str(hash_id).strip()
            name = str(name).strip()

            # Only expose the name if it is actually user-friendly.
            # Ignore names that are empty, equal to the hash id, or look like hashes.
            if not name or name == hash_id or self._is_hash_like(name):
                continue

            result[hash_id] = name

        return result


    def _zone_display_names(self, task: dict[str, Any]) -> list[str]:
        """Return readable zone names for a schedule, falling back to hash ids."""

        zone_hash_ids = task.get("zoneHashIds") or []
        name_map = self._zone_name_map()

        names: list[str] = []

        for zone_hash_id in zone_hash_ids:
            zone_hash_id = str(zone_hash_id)
            readable_name = name_map.get(zone_hash_id)

            if readable_name:
                names.append(readable_name)
            else:
                names.append(zone_hash_id)

        return names


class LymowClearErrorButton(_LymowButton):
    """Clear/acknowledge a mower error so a task can resume. Sends a Pause
    (userCtrl=3) — exactly what the app's contextual 'Clear Error' button does.
    Available whenever there's an active error: obstacle errors (E74) set
    robotStatus=Error + errorCode but leave workStatus unset, so we check all
    three (the old workStatus-only gate kept the button grayed out during a
    real error)."""

    _attr_name = "Clear Error"
    _attr_icon = "mdi:alert-circle-check-outline"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_clear_error")

    @property
    def available(self) -> bool:
        d = self.coordinator.data or {}
        return super().available and (
            d.get("workStatus") in (WORK_STATUS_ERROR, WORK_STATUS_EMERGENCY_STOP)
            or d.get("robotStatus") in (WORK_STATUS_ERROR, WORK_STATUS_EMERGENCY_STOP)
            or bool(d.get("errorCode"))
        )

    async def async_press(self) -> None:
        _LOGGER.debug("Lymow Clear Error button pressed")
        await self.coordinator.async_clear_error()


class LymowOtaUpdateButton(_LymowButton):
    """Trigger a firmware OTA (userCtrl=26). Grayed out unless the mower has an
    update pending. (The Firmware entity's Install button does the same, but HA
    only surfaces it when latest > installed.)"""

    _attr_name = "Update Firmware"
    _attr_icon = "mdi:cellphone-arrow-down"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_ota_update")

    @property
    def available(self) -> bool:
        d = self.coordinator.data or {}
        latest = d.get("latestFw")
        installed = d.get("softwareVersion")
        return super().available and bool(latest) and latest != installed

    async def async_press(self) -> None:
        _LOGGER.debug("Lymow Update Firmware button pressed")
        await self.coordinator.async_ota_update()


class LymowAbortOtaButton(_LymowButton):
    """Abort an in-progress firmware OTA (userCtrl=27). Available only while the
    mower is updating (workStatus=11)."""

    _attr_name = "Abort Firmware Update"
    _attr_icon = "mdi:cancel"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_abort_ota")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.work_status == WORK_STATUS_UPDATING

    async def async_press(self) -> None:
        _LOGGER.debug("Lymow Abort Firmware Update button pressed")
        await self.coordinator.async_abort_ota()
