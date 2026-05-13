"""Lymow time platform — Auto recharge schedule times."""

from __future__ import annotations

from datetime import time
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
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
            LymowRrStartTime(coord),
            LymowRrEndTime(coord),
        ],
        update_before_add=False,
    )


def _read_time(data: dict[str, Any], key: str) -> time | None:
    value = data.get(key)
    if not isinstance(value, dict):
        return None

    try:
        hour = int(value.get("hour", 0))
        minute = int(value.get("minute", 0))
    except (TypeError, ValueError):
        return None

    hour = max(0, min(23, hour))
    minute = max(0, min(59, minute))

    return time(hour=hour, minute=minute)


class LymowRrStartTime(LymowEntity, TimeEntity):
    """Auto recharge resume period start time."""

    _attr_name = "Auto Recharge Start Time"
    _attr_icon = "mdi:clock-start"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "auto_recharge_start_time")

    @property
    def native_value(self) -> time | None:
        return _read_time(self.coordinator.data or {}, "rrResumePeriodStart")

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_set_rr_start_time(value.hour, value.minute)


class LymowRrEndTime(LymowEntity, TimeEntity):
    """Auto recharge resume period end time."""

    _attr_name = "Auto Recharge End Time"
    _attr_icon = "mdi:clock-end"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "auto_recharge_end_time")

    @property
    def native_value(self) -> time | None:
        return _read_time(self.coordinator.data or {}, "rrResumePeriodEnd")

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_set_rr_end_time(value.hour, value.minute)