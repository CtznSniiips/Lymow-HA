"""Lymow sensor platform."""
from __future__ import annotations

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


# ── Platform setup ────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: LymowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [LymowSensor(coord, desc) for desc in SENSORS],
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
