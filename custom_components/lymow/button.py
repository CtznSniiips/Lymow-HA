"""Lymow button platform.

Command buttons call the coordinator methods instead of publishing protobuf
payloads directly, so command preflight/watchdog logic stays in one place.
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import LymowCoordinator
from .entity_base import LymowEntity
from .protocol import encode_query_map, encode_query_robot_config, encode_query_schedules

_LOGGER = logging.getLogger(__name__)


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
            LymowRefreshMapButton(coord),
            LymowRefreshRobotConfigButton(coord),
            LymowRefreshSchedulesButton(coord),
            LymowRefreshDeviceInfoButton(coord),
            LymowRefreshHistoryButton(coord),
        ],
        update_before_add=False,
    )


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
    """Return to dock and keep task progress when possible."""

    _attr_name = "Dock"
    _attr_icon = "mdi:home-import-outline"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_dock")

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
