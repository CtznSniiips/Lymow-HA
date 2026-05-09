"""Lymow device tracker platform — real robot GPS/RTK position."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

try:
    from homeassistant.components.device_tracker.config_entry import TrackerEntity
except ImportError:  # older HA fallback
    from homeassistant.components.device_tracker import TrackerEntity  # type: ignore

try:
    from homeassistant.components.device_tracker.const import SourceType
except ImportError:  # older HA fallback
    from homeassistant.components.device_tracker import SourceType  # type: ignore

from .const import DOMAIN
from .coordinator import LymowCoordinator
from .entity_base import LymowEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: LymowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LymowRobotTracker(coord)], update_before_add=False)


class LymowRobotTracker(LymowEntity, TrackerEntity):
    """GPS/RTK position of the mower robot.

    Source data comes from PbOutput.robotLlaCoords, root field 26:
      latitude  = field 1 float
      longitude = field 2 float
      altitude  = field 3 float
    """

    _attr_name = "Robot Position"
    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "robot_position")

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def available(self) -> bool:
        d = self.coordinator.data or {}
        return (
            self.coordinator.last_update_success
            and self.coordinator.is_online
            and self.latitude is not None
            and self.longitude is not None
        )

    @property
    def latitude(self) -> float | None:
        d = self.coordinator.data or {}
        v = (d.get("robotLlaCoords") or {}).get("latitude") or d.get("latitude")
        return float(v) if v is not None else None

    @property
    def longitude(self) -> float | None:
        d = self.coordinator.data or {}
        v = (d.get("robotLlaCoords") or {}).get("longitude") or d.get("longitude")
        return float(v) if v is not None else None

    @property
    def altitude(self) -> float | None:
        d = self.coordinator.data or {}
        v = (d.get("robotLlaCoords") or {}).get("altitude") or d.get("altitude")
        return float(v) if v is not None else None

    @property
    def location_accuracy(self) -> float | None:
        d = self.coordinator.data or {}
        rtk = d.get("rtkDiagnosticL1") or {}
        v = rtk.get("precision") or (d.get("localizationInfo") or {}).get("horizontalAccuracy")
        return float(v) if v is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        attrs: dict[str, Any] = {}

        if self.altitude is not None:
            attrs["altitude"] = self.altitude
        if self.location_accuracy is not None:
            attrs["gps_accuracy_m"] = self.location_accuracy
        if rtk := d.get("rtkStatus"):
            attrs["rtk_status_code"] = rtk
        if robot_loc := d.get("robotLoc") or d.get("robotPosePib"):
            attrs["local_map_position"] = robot_loc
        if enu := (d.get("btMap") or {}).get("enuBasePoint"):
            attrs["enu_base_point"] = enu
        if lla := d.get("robotLlaCoords"):
            attrs["robot_lla_coords"] = lla

        return attrs
