"""Lymow sensor platform."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfArea, UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CLEAN_MODE_ADAPTIVE_ZIGZAG,
    CLEAN_MODE_CHESS_BOARD,
    CLEAN_MODE_PERIMETER_ONLY,
    CLEAN_MODE_ZIGZAG,
    DOMAIN,
    F_BATTERY,
    F_CLEAN_AREA,
    F_CLEAN_MODE,
    F_CUT_HEIGHT,
    F_ERROR_CODE,
    F_FW_VERSION,
    F_IP_ADDRESS,
    F_LTE_SIGNAL,
    F_MAC,
    F_MCU_VERSION,
    F_NET_DETAIL,
    F_RTK_STATUS,
    F_SERIAL_NO,
    F_WIFI_SIGNAL,
    NET_SIM_SIGNAL,
    NET_WIFI_SIGNAL,
    RTK_STATUS_LABELS,
    RTSP_PATH,
    RTSP_PORT,
    error_label,
)
from .coordinator import LymowCoordinator
from .entity_base import LymowEntity

# ── Label maps ────────────────────────────────────────────────

CLEAN_MODE_LABELS: dict[str, str] = {
    CLEAN_MODE_ZIGZAG:          "Zigzag",
    CLEAN_MODE_CHESS_BOARD:     "Chess Board",
    CLEAN_MODE_PERIMETER_ONLY:  "Perimeter Only",
    CLEAN_MODE_ADAPTIVE_ZIGZAG: "Adaptive Zigzag",
}

WORK_STATUS_LABELS: dict[int, str] = {
    -1: "Offline",
    0:  "Idle",
    1:  "Waiting",
    2:  "Mowing",
    3:  "Paused",
    4:  "Docking",
    5:  "Charging",
    6:  "Remote Control",
    7:  "Error",
    8:  "Resuming",
    9:  "Zone Partitioning",
    10: "Pause Docking",
    11: "Updating",
    12: "Fully Charged",
    13: "Emergency Stop",
    14: "Escaping",
    15: "RTT Test",
}

NET_TYPE_LABELS: dict[int, str] = {0: "None", 1: "WiFi", 2: "LTE"}


# ── Descriptor ────────────────────────────────────────────────

@dataclass(frozen=True, kw_only=True)
class LymowSensorDesc(SensorEntityDescription):
    value_source: str | Callable[[dict], Any] = ""
    transform: Callable[[Any], Any] | None = None


# ── Helpers ───────────────────────────────────────────────────

def _net(key: str) -> Callable[[dict], Any]:
    return lambda d: (d.get(F_NET_DETAIL) or {}).get(key)

def _rtk(key: str) -> Callable[[dict], Any]:
    return lambda d: (d.get("rtkDiagnosticL1") or {}).get(key)

def _robot_ip(d: dict) -> str | None:
    """Robot IP — top-level ipAddress, fallback netDetailInfo.wifiIp."""
    return d.get(F_IP_ADDRESS) or (d.get(F_NET_DETAIL) or {}).get("wifiIp")

def _pose(key: str) -> Callable[[dict], Any]:
    return lambda d: (d.get("pose") or d.get("robotLoc") or d.get("robotPosePib") or {}).get(key)

def _enu(key: str) -> Callable[[dict], Any]:
    return lambda d: (d.get("enu_base_point") or (d.get("btMap") or {}).get("enuBasePoint") or {}).get(key)

def _history_summary(key: str) -> Callable[[dict], Any]:
    return lambda d: (d.get("cleanHistorySummary") or {}).get(key)


# ── Sensor definitions ────────────────────────────────────────

SENSORS: tuple[LymowSensorDesc, ...] = (

    # ── Status ───────────────────────────────────────────────────────────
    LymowSensorDesc(
        key="work_status",
        name="Status",
        icon="mdi:robot-mower",
        value_source="workStatus",
        transform=lambda v: WORK_STATUS_LABELS.get(v, f"Unknown ({v})"),
    ),
    LymowSensorDesc(
        key="error",
        name="Error",
        icon="mdi:alert-circle-outline",
        value_source=F_ERROR_CODE,
        transform=lambda v: error_label(v) if v else "None",
        entity_registry_enabled_default=False,
    ),

    # ── Battery ──────────────────────────────────────────────────────────
    LymowSensorDesc(
        key="battery",
        name="Battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
        value_source=F_BATTERY,
    ),

    # ── Mowing config ────────────────────────────────────────────────────
    LymowSensorDesc(
        key="clean_mode",
        name="Mow Mode",
        icon="mdi:grass",
        value_source=F_CLEAN_MODE,
        transform=lambda v: CLEAN_MODE_LABELS.get(v, v) if v else None,
    ),
    LymowSensorDesc(
        key="blade_height",
        name="Blade Height",
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:scissors-cutting",
        value_source=F_CUT_HEIGHT,
    ),

    # ── Clean session ────────────────────────────────────────────────────
    LymowSensorDesc(
        key="session_area",
        name="Session Mowed Area",
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-check",
        value_source=F_CLEAN_AREA,
    ),
    LymowSensorDesc(
        key="session_time",
        name="Session Duration",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-outline",
        value_source="cleanTime",
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="session_percent",
        name="Session Progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:progress-check",
        value_source="cleanPercent",
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="session_remain",
        name="Session Remaining",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-sand",
        value_source="remainCleanTime",
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="map_area",
        name="Map Total Area",
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map",
        value_source="mapArea",
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="zone_count",
        name="Zone Count",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-multiple",
        value_source=lambda d: (d.get("btMap") or {}).get("zone_count"),
        entity_registry_enabled_default=False,
    ),

    # ── GPS / RTK ─────────────────────────────────────────────────────────
    LymowSensorDesc(
        key="rtk_status",
        name="RTK GPS",
        icon="mdi:satellite-uplink",
        value_source=F_RTK_STATUS,
        transform=lambda v: RTK_STATUS_LABELS.get(v, f"Unknown ({v})"),
    ),
    LymowSensorDesc(
        key="rtk_precision",
        name="RTK Precision",
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:crosshairs-gps",
        value_source=_rtk("precision"),
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="rtk_satellites",
        name="RTK Satellites",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:satellite-variant",
        value_source=_rtk("satelliteCount"),
        entity_registry_enabled_default=False,
    ),

    # ── Connectivity ──────────────────────────────────────────────────────
    LymowSensorDesc(
        key="wifi_signal",
        name="WiFi Signal",
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:wifi",
        value_source=lambda d: d.get(F_WIFI_SIGNAL) or _net(NET_WIFI_SIGNAL)(d),
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="lte_signal",
        name="4G Signal",
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:signal-4g",
        value_source=lambda d: d.get(F_LTE_SIGNAL) or _net(NET_SIM_SIGNAL)(d),
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="network_type",
        name="Network Type",
        icon="mdi:network",
        value_source=lambda d: NET_TYPE_LABELS.get(
            _net("currentNet")(d), f"Unknown ({_net('currentNet')(d)})"
        ) if _net("currentNet")(d) is not None else None,
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="wifi_name",
        name="WiFi Network",
        icon="mdi:wifi-settings",
        value_source=_net("wifiName"),
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="sim_iccid",
        name="SIM ICCID",
        icon="mdi:sim",
        value_source=_net("simIccid"),
        entity_registry_enabled_default=False,
    ),

    # ── Firmware / Device identity ────────────────────────────────────────
    LymowSensorDesc(
        key="fw_version",
        name="Firmware",
        icon="mdi:chip",
        value_source=F_FW_VERSION,   # top-level string ("app2.3.9 bl0.0.1")
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="mcu_version",
        name="MCU Version",
        icon="mdi:memory",
        value_source=F_MCU_VERSION,  # top-level string ("v2.1.42_beta")
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="serial_number",
        name="Serial Number",
        icon="mdi:identifier",
        value_source=F_SERIAL_NO,
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="mac_address",
        name="MAC Address",
        icon="mdi:ethernet",
        value_source=F_MAC,
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="wheel_version",
        name="Wheel Version",
        icon="mdi:tire",
        value_source="wheelVer",
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="knife_version",
        name="Blade Version",
        icon="mdi:scissors-cutting",
        value_source="knifeVer",
        entity_registry_enabled_default=False,
    ),


    # ── Position / Map frame ───────────────────────────────────────────────
    LymowSensorDesc(
        key="derived_latitude",
        name="Derived Latitude",
        icon="mdi:latitude",
        value_source="derivedLatitude",
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="derived_longitude",
        name="Derived Longitude",
        icon="mdi:longitude",
        value_source="derivedLongitude",
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="robot_local_x",
        name="Robot Local X",
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:axis-x-arrow",
        value_source=_pose("x"),
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="robot_local_y",
        name="Robot Local Y",
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:axis-y-arrow",
        value_source=_pose("y"),
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="robot_heading",
        name="Robot Heading",
        icon="mdi:compass",
        value_source=lambda d: (d.get("pose") or d.get("robotLoc") or {}).get("heading")
            or (d.get("pose") or d.get("robotLoc") or {}).get("theta"),
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="current_zone",
        name="Current Zone",
        icon="mdi:map-marker-radius",
        value_source="currentZone",
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="enu_base_latitude",
        name="RTK Base Latitude",
        icon="mdi:satellite-uplink",
        value_source=_enu("latitude"),
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="enu_base_longitude",
        name="RTK Base Longitude",
        icon="mdi:satellite-uplink",
        value_source=_enu("longitude"),
        entity_registry_enabled_default=False,
    ),

    # ── REST history / cloud summary ───────────────────────────────────────
    LymowSensorDesc(
        key="clean_history_records",
        name="Clean History Records",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:history",
        value_source="cleanHistoryTotalRecords",
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="total_clean_time",
        name="Total Clean Time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-outline",
        value_source=_history_summary("total_clean_time"),
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="total_clean_area",
        name="Total Clean Area",
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-check",
        value_source=_history_summary("total_clean_area"),
        entity_registry_enabled_default=False,
    ),
    # ── Network / Camera ──────────────────────────────────────────────────
    LymowSensorDesc(
        key="ip_address",
        name="IP Address",
        icon="mdi:ip-network",
        # ipAddress is top-level in the MQTT state dict (from PbDeviceProfile.5)
        # Fallback: netDetailInfo.wifiIp
        value_source=_robot_ip,
        entity_registry_enabled_default=False,
    ),
    LymowSensorDesc(
        key="rtsp_url",
        name="Camera URL",
        icon="mdi:cctv",
        # Built as: rtsp://<ip>:<RTSP_PORT>/<RTSP_PATH>
        # Use with go2rtc or a Generic Camera integration.
        value_source=lambda d: (
            f"rtsp://{ip}:{RTSP_PORT}/{RTSP_PATH}"
            if (ip := _robot_ip(d))
            else None
        ),
        entity_registry_enabled_default=False,
    ),
)


# ── ENU → WGS84 helpers (used by LymowMapGeoJsonSensor) ───────

_WGS84_A = 6_378_137.0   # equatorial radius [m]


def _enu_to_latlon(
    east_m: float, north_m: float, lat0_deg: float, lon0_deg: float
) -> tuple[float, float]:
    """Convert ENU metres to WGS84 lat/lon (accurate to < 1 cm at garden scale)."""
    lat0 = math.radians(lat0_deg)
    dlat = math.degrees(north_m / _WGS84_A)
    dlon = math.degrees(east_m  / (_WGS84_A * math.cos(lat0)))
    return lat0_deg + dlat, lon0_deg + dlon


def _sf(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except Exception:
        return None


def _safe_pts(points: list[Any]) -> list[tuple[float, float]]:
    """Normalise zone points: dicts {x,y} or tuples/lists (x, y)."""
    out: list[tuple[float, float]] = []
    for p in points:
        if isinstance(p, dict):
            x, y = _sf(p.get("x")), _sf(p.get("y"))
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            x, y = _sf(p[0]), _sf(p[1])
        else:
            continue
        if x is not None and y is not None:
            out.append((x, y))
    return out


def _pts_to_ring(
    pts: list[tuple[float, float]], lat0: float, lon0: float
) -> list[list[float]]:
    ring = []
    for x, y in pts:
        lat, lon = _enu_to_latlon(x, y, lat0, lon0)
        ring.append([round(lon, 8), round(lat, 8)])
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


# ── Platform setup ────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: LymowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [LymowSensor(coord, desc) for desc in SENSORS] + [LymowMapGeoJsonSensor(coord)],
        update_before_add=False,
    )


class LymowSensor(LymowEntity, SensorEntity):
    """Generic Lymow sensor — driven by LymowSensorDesc."""

    entity_description: LymowSensorDesc

    def __init__(self, coordinator: LymowCoordinator, desc: LymowSensorDesc) -> None:
        super().__init__(coordinator, desc.key)
        self.entity_description = desc

    @property
    def native_value(self) -> Any:
        d = self.coordinator.data or {}
        src = self.entity_description.value_source
        raw = src(d) if callable(src) else d.get(src)
        if raw is None:
            return None
        if fn := self.entity_description.transform:
            return fn(raw)
        return raw


class LymowMapGeoJsonSensor(LymowEntity, SensorEntity):
    """Exposes the Lymow zone map as a GeoJSON FeatureCollection.

    State  : "<N> zones"
    Attr   : geojson → FeatureCollection (WGS84 when enuBasePoint available)

    Consumed by custom Lovelace map cards and by the Flutter control app
    via HA WebSocket / REST.
    """

    _attr_name = "Map GeoJSON"
    _attr_icon = "mdi:map-marker-path"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "map_geojson")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> str:
        btmap = (self.coordinator.data or {}).get("btMap") or {}
        zones = btmap.get("zones") or []
        drawable = sum(1 for z in zones if z.get("points") and len(z.get("points") or []) >= 3)
        return f"{drawable} zones"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data  = self.coordinator.data or {}
        btmap = data.get("btMap") or {}
        zones = btmap.get("zones") or []

        # enuBasePoint: {latitude, longitude, altitude} — set by _decode_lla_dict
        ebp  = btmap.get("enuBasePoint") or data.get("enu_base_point") or {}
        lat0 = _sf(ebp.get("latitude"))
        lon0 = _sf(ebp.get("longitude"))
        has_origin = lat0 is not None and lon0 is not None

        features: list[dict[str, Any]] = []

        # Zone polygons
        for idx, zone in enumerate(zones):
            pts = _safe_pts(zone.get("points") or [])
            if len(pts) < 3:
                continue
            props: dict[str, Any] = {
                "type":     "zone",
                "name":     zone.get("name") or zone.get("hashId") or str(idx),
                "hashId":   zone.get("hashId"),
                "zoneType": zone.get("zoneType"),
            }
            if cfg := zone.get("zoneConfig"):
                props["zoneConfig"] = cfg
            if has_origin:
                geometry: dict[str, Any] = {
                    "type":        "Polygon",
                    "coordinates": [_pts_to_ring(pts, lat0, lon0)],
                }
            else:
                geometry = {
                    "type":        "Polygon",
                    "coordinates": [[[p[0], p[1]] for p in pts] + [list(pts[0])]],
                    "_crs":        "ENU_metres",
                }
            features.append({"type": "Feature", "properties": props, "geometry": geometry})

        # Dock
        dock = data.get("chargingStationLoc")
        if isinstance(dock, dict):
            x, y = _sf(dock.get("x")), _sf(dock.get("y"))
            if x is not None and y is not None:
                if has_origin:
                    lat, lon = _enu_to_latlon(x, y, lat0, lon0)
                    coords: list[float] = [round(lon, 8), round(lat, 8)]
                else:
                    coords = [x, y]
                features.append({
                    "type": "Feature",
                    "properties": {"type": "dock", "name": "Dock", "heading": _sf(dock.get("heading"))},
                    "geometry": {"type": "Point", "coordinates": coords},
                })

        # Robot position
        robot = data.get("robotLoc") or data.get("pose") or data.get("robotPosePib")
        if isinstance(robot, dict):
            x, y = _sf(robot.get("x")), _sf(robot.get("y"))
            if x is not None and y is not None:
                if has_origin:
                    lat, lon = _enu_to_latlon(x, y, lat0, lon0)
                    coords = [round(lon, 8), round(lat, 8)]
                else:
                    coords = [x, y]
                features.append({
                    "type": "Feature",
                    "properties": {
                        "type":    "robot",
                        "name":    "Robot",
                        "heading": _sf(robot.get("heading") or robot.get("theta")),
                    },
                    "geometry": {"type": "Point", "coordinates": coords},
                })
                
        # Mow path (current/last session)
        mow_path = getattr(self.coordinator, "mow_path", [])
        if len(mow_path) >= 2:
            if has_origin:
                line_coords = []
                for x, y in mow_path:
                    lat, lon = _enu_to_latlon(x, y, lat0, lon0)
                    line_coords.append([round(lon, 8), round(lat, 8)])
            else:
                line_coords = [[p[0], p[1]] for p in mow_path]
            features.append({
                "type": "Feature",
                "properties": {
                    "type":        "mow_path",
                    "name":        "Mow Path",
                    "point_count": len(mow_path),
                },
                "geometry": {
                    "type":        "LineString",
                    "coordinates": line_coords,
                },
            })

        return {
            "geojson": {"type": "FeatureCollection", "features": features},
            "zone_count":      len(features),
            "has_gps_origin":  has_origin,
            "enu_base_point":  ebp or None,
        }
