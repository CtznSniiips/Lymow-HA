"""Lymow select platform.

Includes:
  - Mow Mode select
  - Backup Map select: choose which S3 backup map to download/render
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
    async_add_entities(
        [
            LymowCleanModeSelect(coord),
            LymowBackupMapSelect(coord),
        ],
        update_before_add=False,
    )


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


class LymowBackupMapSelect(LymowEntity, SelectEntity):
    """Select which cloud backup map should be loaded from S3."""

    _attr_name = "Backup Map"
    _attr_icon = "mdi:map-clock"
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "backup_map_select")

    @property
    def options(self) -> list[str]:
        return list(self.coordinator.backup_map_options)

    @property
    def current_option(self) -> str | None:
        return self.coordinator.current_backup_map_option

    @property
    def available(self) -> bool:
        return super().available and bool(self.options)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_select_backup_map(option)

    @property
    def extra_state_attributes(self) -> dict:
        d = self.coordinator.data or {}
        loaded = d.get("loadedBackupMap") if isinstance(d, dict) else None
        return {
            "selected_map_file": d.get("selectedBackupMapFile"),
            "loaded_map_file": loaded.get("map_file") if isinstance(loaded, dict) else None,
            "loaded_map_name": loaded.get("name") if isinstance(loaded, dict) else None,
            "backup_map_count": len(d.get("backupMapList") or []),
            "backup_map_bytes": d.get("backupMapBytes"),
            "backup_map_error": d.get("backupMapDownloadError"),
        }
