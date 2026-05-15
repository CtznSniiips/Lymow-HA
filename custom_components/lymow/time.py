"""Lymow time platform — Auto recharge schedule times."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

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
    """Read a raw UTC time dict from coordinator data."""
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


def _utc_time_to_local(utc_t: time, ha_tz: ZoneInfo) -> time:
    """Convert a naive UTC time-of-day to the HA local timezone."""
    today_utc = datetime.now(timezone.utc).date()
    utc_dt = datetime.combine(today_utc, utc_t, tzinfo=timezone.utc)
    return utc_dt.astimezone(ha_tz).time().replace(tzinfo=None)


def _local_time_to_utc(local_t: time, ha_tz: ZoneInfo) -> time:
    """Convert a naive local time-of-day (HA timezone) to UTC."""
    today_local = datetime.now(ha_tz).date()
    local_dt = datetime.combine(today_local, local_t, tzinfo=ha_tz)
    return local_dt.astimezone(timezone.utc).time().replace(tzinfo=None)


class LymowRrStartTime(LymowEntity, TimeEntity):
    """Auto recharge resume period start time."""

    _attr_name = "Auto Recharge Start Time"
    _attr_icon = "mdi:clock-start"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "auto_recharge_start_time")

    @property
    def _ha_tz(self) -> ZoneInfo:
        return dt_util.get_time_zone(self.coordinator.hass.config.time_zone)

    @property
    def native_value(self) -> time | None:
        utc_t = _read_time(self.coordinator.data or {}, "rrResumePeriodStart")
        if utc_t is None:
            return None
        return _utc_time_to_local(utc_t, self._ha_tz)

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    async def async_set_value(self, value: time) -> None:
        utc_t = _local_time_to_utc(value, self._ha_tz)
        await self.coordinator.async_set_rr_start_time(utc_t.hour, utc_t.minute)


class LymowRrEndTime(LymowEntity, TimeEntity):
    """Auto recharge resume period end time."""

    _attr_name = "Auto Recharge End Time"
    _attr_icon = "mdi:clock-end"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "auto_recharge_end_time")

    @property
    def _ha_tz(self) -> ZoneInfo:
        return dt_util.get_time_zone(self.coordinator.hass.config.time_zone)

    @property
    def native_value(self) -> time | None:
        utc_t = _read_time(self.coordinator.data or {}, "rrResumePeriodEnd")
        if utc_t is None:
            return None
        return _utc_time_to_local(utc_t, self._ha_tz)

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    async def async_set_value(self, value: time) -> None:
        utc_t = _local_time_to_utc(value, self._ha_tz)
        await self.coordinator.async_set_rr_end_time(utc_t.hour, utc_t.minute)