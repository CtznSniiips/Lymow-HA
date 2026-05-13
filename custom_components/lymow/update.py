"""Lymow update platform — firmware OTA notification.

Uses HA's UpdateEntity (Platform.UPDATE) to show available firmware
updates in the Updates panel and trigger push notifications.

The update check calls the Lymow checkUpdateApi REST endpoint.
Install is not supported from HA (OTA must be triggered from the
official app); the entity is purely informational.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import LymowCoordinator
from .entity_base import LymowEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: LymowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LymowFirmwareUpdate(coord)], update_before_add=False)


class LymowFirmwareUpdate(LymowEntity, UpdateEntity):
    """Lymow firmware update entity.

    Checks for OTA updates via the Lymow REST API on every REST poll
    cycle. Shows up in HA's Updates dashboard panel and sends a push
    notification when a new version is available.

    Install is not implemented — OTA must be triggered from the
    official Lymow app.
    """

    _attr_name         = "Firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    # No INSTALL feature — we can't trigger OTA from HA
    _attr_supported_features = UpdateEntityFeature.RELEASE_NOTES

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "firmware_update")

    # ── installed version ────────────────────────────────────────

    @property
    def installed_version(self) -> str | None:
        d = self.coordinator.data or {}
        return (
            d.get("softwareVersion") or ""
        )

    # ── latest version (from check_update REST call) ─────────────

    @property
    def latest_version(self) -> str | None:
        d = self.coordinator.data or {}
        latest = d.get("latestFw")
        if not latest:
            return self.installed_version  # no update known → report same
        return latest

    # ── release notes ────────────────────────────────────────────

    def release_notes(self) -> str | None:
        d = self.coordinator.data or {}
        note = d.get("releaseNote")
        if not note:
            return None
        return str(note).replace("\\n", "\n")
    # ── extra attributes ─────────────────────────────────────────

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        return {
            "mcu_version":      d.get("softwareVersion"),
            "latest_fw":        d.get("latestFw"),
            "release_note":     d.get("releaseNote"),
        }