"""Lymow device tracker entities.

Exposes:
  - RTK base station GPS position from btMap.enuBasePoint
  - Live mower GPS position derived from enuBasePoint + local pose

The live mower position falls back to REST get_device_info.robotLocation or
PbOutput.robotLlaCoords if the local pose/base pair is not available yet.
"""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import LymowCoordinator
from .entity_base import LymowEntity
from .state import get_enu_base_point, get_robot_pose, robot_gps_from_state


def _read_float(obj, key: str) -> float | None:
    if obj is None:
        return None
    try:
        value = obj.get(key) if isinstance(obj, dict) else getattr(obj, key)
    except Exception:
        return None
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


class _LymowTrackerBase(LymowEntity, TrackerEntity, RestoreEntity):
    """Base tracker with RestoreEntity fallback after HA restart."""

    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator: LymowCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._restored_lat: float | None = None
        self._restored_lon: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.attributes:
            try:
                lat = last.attributes.get("latitude")
                lon = last.attributes.get("longitude")
                if lat is not None:
                    self._restored_lat = float(lat)
                if lon is not None:
                    self._restored_lon = float(lon)
            except (TypeError, ValueError):
                pass


class LymowRtkBaseTracker(_LymowTrackerBase):
    """RTK base station GPS anchor."""

    _attr_name = "RTK Base"
    _attr_icon = "mdi:satellite-uplink"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def latitude(self) -> float | None:
        ebp = get_enu_base_point(self.coordinator.data or {})
        lat = _read_float(ebp, "latitude")
        if lat is not None:
            return lat
        return self._restored_lat

    @property
    def longitude(self) -> float | None:
        ebp = get_enu_base_point(self.coordinator.data or {})
        lon = _read_float(ebp, "longitude")
        if lon is not None:
            return lon
        return self._restored_lon


class LymowMowerTracker(_LymowTrackerBase):
    """Live mower GPS derived from local pose + RTK ENU base point."""

    _attr_name = "Mower Position"
    _attr_icon = "mdi:robot-mower"

    def _coords(self) -> tuple[float, float] | None:
        return robot_gps_from_state(self.coordinator.data or {})

    def _heading(self) -> float | None:
        pose = get_robot_pose(self.coordinator.data or {})
        if pose is None:
            return None

        heading = _read_float(pose, "heading")
        if heading is not None:
            return heading

        return _read_float(pose, "theta")

    @property
    def latitude(self) -> float | None:
        live = self._coords()
        if live is not None:
            return live[0]
        return self._restored_lat

    @property
    def longitude(self) -> float | None:
        live = self._coords()
        if live is not None:
            return live[1]
        return self._restored_lon

    @property
    def extra_state_attributes(self) -> dict[str, float]:
        if (heading := self._heading()) is None:
            return {}
        return {"heading": heading}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: LymowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            LymowRtkBaseTracker(coord, "rtk_base"),
            LymowMowerTracker(coord, "mower_position"),
        ],
        update_before_add=False,
    )
