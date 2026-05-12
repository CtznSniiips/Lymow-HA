"""Lymow number platform — Blade Height (read-only, derived from first zone config).

cutHeight has no global firmware setting — each zone has its own value.
This sensor shows the cutHeight of the first zone that has one configured,
as a read-only indicator. Write support is not implemented because the
firmware has no "set global blade height" command.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, F_CUT_HEIGHT
from .coordinator import LymowCoordinator
from .entity_base import LymowEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: LymowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LymowBladeHeight(coord)], update_before_add=False)


class LymowBladeHeight(LymowEntity, NumberEntity):
    """Blade height indicator (read-only, from first zone's zoneConfig).

    The Lymow firmware does not expose a global blade height command.
    cutHeight is a per-zone setting; this entity shows the value from the
    first zone that has one configured, updated whenever the map is loaded.
    """

    _attr_name                       = "Blade Height"
    _attr_icon                       = "mdi:scissors-cutting"
    _attr_native_min_value           = 20
    _attr_native_max_value           = 100
    _attr_native_step                = 5
    _attr_native_unit_of_measurement = UnitOfLength.MILLIMETERS
    _attr_mode                       = NumberMode.BOX
    _attr_entity_category            = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "blade_height")

    @property
    def native_value(self) -> float | None:
        d = self.coordinator.data or {}
        # _derive_state populates cutHeight from first zone's zoneConfig
        val = d.get(F_CUT_HEIGHT)
        if val is not None:
            return float(val)
        # Direct fallback: walk zones ourselves
        zones = (d.get("btMap") or {}).get("zones") or []
        for z in zones:
            ch = (z.get("zoneConfig") or {}).get("cutHeight")
            if ch is not None:
                return float(ch)
        return None

    async def async_set_native_value(self, value: float) -> None:
        # No global set command exists in firmware — this is a no-op.
        # Implement per-zone writes when encode_set_zone_config is available.
        pass