"""Lymow update platform — firmware OTA notification.

Uses HA's UpdateEntity (Platform.UPDATE) to show available firmware
updates in the Updates panel and trigger push notifications.

The update check calls the Lymow checkUpdateApi REST endpoint. Install is
supported: it replicates the official app's cloud OTA flow (check-update ->
create-ota-job -> poll the AWS IoT Job), with live progress from MQTT telemetry.
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
from homeassistant.const import EntityCategory
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

    Install replicates the app's cloud OTA flow (AWS IoT Job) and reports
    live progress from MQTT downloadProgress telemetry.
    """

    _attr_name         = "Firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.CONFIG
    # OTA is triggered exactly like the official app: a cloud REST call creates
    # an AWS IoT Job (check-update -> create-ota-job -> poll). HA only shows the
    # Install button when latest_version > installed_version, so it can't fire
    # unless an update is genuinely available. Live % comes from MQTT telemetry
    # (downloadProgress), surfaced via PROGRESS.
    _attr_supported_features = (
        UpdateEntityFeature.RELEASE_NOTES
        | UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
    )

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "firmware_update")

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Trigger the firmware OTA via the cloud IoT-Job flow (see coordinator)."""
        _LOGGER.info("Lymow firmware OTA install requested for %s", self.coordinator.thing_name)
        await self.coordinator.async_ota_update()

    # ── progress ─────────────────────────────────────────────────

    @property
    def in_progress(self) -> bool:
        d = self.coordinator.data or {}
        return str(d.get("ota_status") or "").lower() in ("queued", "in_progress")

    @property
    def update_percentage(self) -> float | None:
        """Live OTA percentage from MQTT downloadProgress. The app renders an
        indeterminate spinner at 0 and >=90, a number in between — mirror that
        by returning None outside the 1-89 range so HA shows indeterminate."""
        d = self.coordinator.data or {}
        if str(d.get("ota_status") or "").lower() not in ("queued", "in_progress"):
            return None
        try:
            pct = int(d.get("ota_progress"))
        except (TypeError, ValueError):
            return None
        if pct <= 0 or pct >= 90:
            return None
        return float(pct)

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
            "ota_status":       d.get("ota_status"),
            "ota_progress":     d.get("ota_progress"),
            "ota_detail":       d.get("ota_detail"),
            "ota_job_id":       d.get("ota_job_id"),
            "fw_prefix":        d.get("fwPrefix"),
            "fw_latest_raw":    d.get("fwLatestRaw"),
        }