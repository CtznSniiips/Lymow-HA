"""Lymow number platform — Blade Height."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_CHANNEL_BUFFER_M, DOMAIN, F_CUT_HEIGHT
from .coordinator import LymowCoordinator
from .entity_base import LymowEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: LymowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            LymowBladeHeight(coord),
            LymowRechargeThreshold(coord),
            LymowResumeThreshold(coord),
            LymowChannelBuffer(coord),
        ],
        update_before_add=False)


class LymowChannelBuffer(LymowEntity, NumberEntity):
    """How far (metres) outside a channel polygon the mower still counts as being
    'in' the channel. Lymow's channel polygons are coarse/thin, so a strict
    inside test misses fast passes; this buffer makes thin corridors reliable
    triggers for transit automations (gates/doors). Local setting — not sent to
    the mower. 0 = strict inside only."""

    _attr_name = "Channel Detection Buffer"
    _attr_icon = "mdi:vector-polyline-plus"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 5.0
    _attr_native_step = 0.25
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "channel_buffer_m")

    @property
    def native_value(self) -> float | None:
        val = (self.coordinator.data or {}).get("channel_buffer_m")
        return float(val) if val is not None else DEFAULT_CHANNEL_BUFFER_M

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.set_channel_buffer_m(value)


class LymowBladeHeight(LymowEntity, NumberEntity):
    """Blade height control (mm).

    Reads from PbRunTimeConfig.cutHeight (QUERY_MAP response) or
    PbBaseOutput.cutHeight (real-time broadcast) or PbRobotConfig.rcCutHeight.
    Writes via PbInput.map.runTimeConfig.cutHeight (encode_set_cut_height).
    """

    _attr_name                       = "Blade Height"
    _attr_icon                       = "mdi:scissors-cutting"
    _attr_native_min_value           = 20
    _attr_native_max_value           = 100
    _attr_native_step                = 5
    _attr_native_unit_of_measurement = UnitOfLength.MILLIMETERS
    _attr_mode                       = NumberMode.BOX

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "blade_height")

    @property
    def native_value(self) -> float | None:
        d = self.coordinator.data or {}
        # Prefer top-level cutHeight (flattened from runTimeConfig or baseOutput)
        val = d.get(F_CUT_HEIGHT)
        if val is not None:
            return float(val)
        # Fallback: walk zones for the first configured zoneConfig.cutHeight
        zones = (d.get("btMap") or {}).get("zones") or []
        for z in zones:
            ch = (z.get("zoneConfig") or {}).get("cutHeight")
            if ch is not None:
                return float(ch)
        return None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_blade_height(int(value))

class LymowRechargeThreshold(LymowEntity, NumberEntity):
    """Battery percentage where mower should go recharge."""

    _attr_name = "Auto Recharge Battery"
    _attr_icon = "mdi:battery-arrow-down"
    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "auto_recharge_battery")

    @property
    def native_value(self) -> float | None:
        val = (self.coordinator.data or {}).get("rrRechargeBat")
        return float(val) if val is not None else None

    @property
    def available(self) -> bool:
        return super().available and (self.coordinator.data or {}).get("rrRechargeBat") is not None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_recharge_threshold(int(value))


class LymowResumeThreshold(LymowEntity, NumberEntity):
    """Battery percentage where mower should resume mowing."""

    _attr_name = "Auto Resume Battery"
    _attr_icon = "mdi:battery-arrow-up"
    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "auto_resume_battery")

    @property
    def native_value(self) -> float | None:
        val = (self.coordinator.data or {}).get("rrResumeBat")
        return float(val) if val is not None else None

    @property
    def available(self) -> bool:
        return super().available and (self.coordinator.data or {}).get("rrResumeBat") is not None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_resume_threshold(int(value))