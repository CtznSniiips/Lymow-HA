"""Lymow select platform.

Only command/config selects live here. The old S3 backup-map selector was
removed because the mower now provides its live map through QUERY_MAP.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CLEAN_MODE_OPTIONS, DOMAIN, F_CLEAN_MODE
from .coordinator import LymowCoordinator
from .entity_base import LymowEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: LymowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        LymowCleanModeSelect(coord),
        LymowVolumeSelect(coord),
        LymowDockRouteSelect(coord),
    ], update_before_add=False)


class LymowCleanModeSelect(LymowEntity, SelectEntity):
    """Select entity for mowing mode."""

    _attr_name = "Mow Mode"
    _attr_icon = "mdi:grass"
    _attr_options = CLEAN_MODE_OPTIONS

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "clean_mode_select")

    @property
    def current_option(self) -> str | None:
        return (self.coordinator.data or {}).get(F_CLEAN_MODE)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_clean_mode(option)


_VOLUME_OPTIONS = ["Mute", "Low", "Medium", "High"]
_VOLUME_TO_INT = {"Mute": 0, "Low": 30, "Medium": 70, "High": 100}
_INT_TO_VOLUME = {0: "Mute", 30: "Low", 70: "Medium", 100: "High"}


class LymowVolumeSelect(LymowEntity, SelectEntity):
    """Select entity for speaker volume."""

    _attr_name = "Speaker Volume"
    _attr_icon = "mdi:volume-high"
    _attr_options = _VOLUME_OPTIONS

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "volume_select")

    @property
    def current_option(self) -> str | None:
        val = (self.coordinator.data or {}).get("audioVolume")
        if val is None:
            return None
        return _INT_TO_VOLUME.get(val, f"{val}%")

    async def async_select_option(self, option: str) -> None:
        vol = _VOLUME_TO_INT.get(option)
        if vol is not None:
            await self.coordinator.async_set_audio_volume(vol)


_DOCK_ROUTE_OPTIONS = ["Direct Route", "Follow Perimeter"]
_DOCK_ROUTE_TO_INT = {"Direct Route": 1, "Follow Perimeter": 0}
_INT_TO_DOCK_ROUTE = {0: "Follow Perimeter", 1: "Direct Route"}


class LymowDockRouteSelect(LymowEntity, SelectEntity):
    """Select entity for return-to-dock route mode."""

    _attr_name = "Return to Dock"
    _attr_icon = "mdi:home-map-marker"
    _attr_options = _DOCK_ROUTE_OPTIONS

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "dock_route_select")

    @property
    def current_option(self) -> str | None:
        val = (self.coordinator.data or {}).get("chargingMode")
        if val is None:
            return "Follow Perimeter"  # Factory default (proto3 zero = not sent)
        return _INT_TO_DOCK_ROUTE.get(val, f"Unknown ({val})")

    async def async_select_option(self, option: str) -> None:
        mode = _DOCK_ROUTE_TO_INT.get(option)
        if mode is not None:
            await self.coordinator.async_set_charging_mode(mode)
