"""Lymow camera platform.

Two camera entities:
  1. LymowMapCamera  — SVG map rendered from decoded PbMap / btMap zone data
  2. LymowRTSPCamera — live video stream via RTSP (requires local network)
"""
from __future__ import annotations

import math
from typing import Any

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    F_CLEAN_ZONE_IDS,
    F_IP_ADDRESS,
    F_NET_DETAIL,
    RTSP_PATH,
    RTSP_PORT,
    WORK_STATUS_OFFLINE,
)
from .coordinator import LymowCoordinator
from .entity_base import LymowEntity

_CANVAS = 500
_PADDING = 28

_C_BG = "#111827"
_C_LAWN = "#1a3a1a"
_C_BOUNDARY = "#4ade80"
_C_ZONE_IDLE = "#22c55e"
_C_ZONE_ACTIVE = "#86efac"
_C_CHARGING = "#f59e0b"
_C_DOCK = "#fbbf24"
_C_ROBOT = "#f97316"
_C_TEXT = "white"

_STATUS_COLOR = {
    -1: "#374151", 0: "#6b7280", 1: "#6b7280",
     2: "#16a34a", 3: "#9333ea", 4: "#2563eb",
     5: "#d97706", 6: "#0891b2", 7: "#dc2626",
     8: "#16a34a", 9: "#16a34a", 10: "#2563eb",
    11: "#d97706", 12: "#0891b2", 13: "#dc2626",
    14: "#9333ea", 15: "#6b7280",
}
_STATUS_LABEL = {
    -1: "OFFLINE", 0: "IDLE", 1: "WAITING", 2: "MOWING",
     3: "PAUSED", 4: "DOCKING", 5: "CHARGING", 6: "REMOTE",
     7: "ERROR", 8: "RESUMING", 9: "MAPPING", 10: "DOCKING",
    11: "UPDATE", 12: "CHARGED", 13: "E-STOP", 14: "ESCAPING",
}


def _get_robot_ip(data: dict) -> str | None:
    return data.get(F_IP_ADDRESS) or (data.get(F_NET_DETAIL) or {}).get("wifiIp")


def _get_robot_loc(data: dict) -> dict | None:
    for key in ("pose", "robotLoc", "robotPosePib"):
        value = data.get(key)
        if isinstance(value, dict) and value.get("x") is not None and value.get("y") is not None:
            return value
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: LymowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [LymowMapCamera(coord), LymowRTSPCamera(coord)],
        update_before_add=False,
    )


class LymowMapCamera(LymowEntity, Camera):
    """SVG map from decoded map data."""

    _attr_name = "Map"
    _attr_icon = "mdi:map"
    _attr_content_type = "image/svg+xml"
    _attr_supported_features = CameraEntityFeature(0)

    def __init__(self, coordinator: LymowCoordinator) -> None:
        LymowEntity.__init__(self, coordinator, "map")
        Camera.__init__(self)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        d = self.coordinator.data or {}
        svg = render_svg(
            btmap=d.get("btMap"),
            charging_loc=d.get("chargingStationLoc"),
            active_zone_ids=set(d.get(F_CLEAN_ZONE_IDS) or []),
            robot_loc=_get_robot_loc(d),
            work_status=d.get("workStatus", WORK_STATUS_OFFLINE),
            rtk_status=d.get("rtkStatus"),
            battery=d.get("battery"),
        )
        return svg.encode("utf-8")

    @property
    def extra_state_attributes(self) -> dict:
        d = self.coordinator.data or {}
        btmap = d.get("btMap") or {}
        attrs: dict[str, Any] = {}

        if btmap.get("zone_count"):
            attrs["zone_count"] = btmap["zone_count"]
        zones = btmap.get("zones", [])
        if zones:
            attrs["zones"] = [
                {"hashId": z.get("hashId"), "name": z.get("name") or z.get("hashId", "")}
                for z in zones
                if isinstance(z, dict) and z.get("hashId")
            ]
        if channels := btmap.get("channels"):
            attrs["channel_count"] = len(channels)
        if ma := d.get("mapArea"):
            attrs["map_area_m2"] = ma
        if pose := _get_robot_loc(d):
            attrs["robot_local_position"] = pose
        if ebp := (btmap.get("enuBasePoint") or d.get("enu_base_point")):
            attrs["enu_base_point"] = ebp
        if loaded := d.get("loadedBackupMap"):
            attrs["loaded_backup_map"] = loaded
        if bytes_count := d.get("backupMapBytes"):
            attrs["backup_map_bytes"] = bytes_count
        if err := d.get("backupMapDownloadError"):
            attrs["backup_map_download_error"] = err
        return attrs


def render_svg(
    btmap: dict | None,
    charging_loc: dict | None,
    active_zone_ids: set[str],
    robot_loc: dict | None,
    work_status: int,
    rtk_status: int | None,
    battery: int | None,
) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_CANVAS} {_CANVAS}" '
        f'width="{_CANVAS}" height="{_CANVAS}">',
        f'<rect width="{_CANVAS}" height="{_CANVAS}" fill="{_C_BG}"/>',
    ]

    zones = (btmap or {}).get("zones", [])
    drawable = [z for z in zones if isinstance(z, dict) and z.get("points") and len(z["points"]) >= 2]

    all_pts: list[tuple[float, float]] = []
    for z in drawable:
        all_pts.extend([(float(x), float(y)) for x, y in z["points"]])
    if charging_loc and charging_loc.get("x") is not None and charging_loc.get("y") is not None:
        all_pts.append((float(charging_loc.get("x", 0)), float(charging_loc.get("y", 0))))
    if robot_loc and robot_loc.get("x") is not None and robot_loc.get("y") is not None:
        all_pts.append((float(robot_loc.get("x", 0)), float(robot_loc.get("y", 0))))

    if not all_pts:
        parts += _placeholder()
        parts.append("</svg>")
        return "\n".join(parts)

    min_x = min(p[0] for p in all_pts)
    max_x = max(p[0] for p in all_pts)
    min_y = min(p[1] for p in all_pts)
    max_y = max(p[1] for p in all_pts)
    w = max_x - min_x or 1
    h = max_y - min_y or 1
    scale = (_CANVAS - _PADDING * 2) / max(w, h)

    def tx(x: float) -> float:
        return (x - min_x) * scale + _PADDING

    def ty(y: float) -> float:
        return (y - min_y) * scale + _PADDING

    def poly(pts: list[tuple[float, float]]) -> str:
        return " ".join(f"{tx(float(x)):.1f},{ty(float(y)):.1f}" for x, y in pts)

    if len(all_pts) >= 3:
        cx = sum(p[0] for p in all_pts) / len(all_pts)
        cy = sum(p[1] for p in all_pts) / len(all_pts)
        hull = sorted(all_pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
        parts.append(
            f'<polygon points="{poly(hull)}" fill="{_C_LAWN}" '
            f'stroke="{_C_BOUNDARY}" stroke-width="1.5" stroke-dasharray="4 2"/>'
        )

    zone_alphas = ["99", "aa", "bb", "99", "88", "aa"]
    for i, zone in enumerate(drawable):
        pts = [(float(x), float(y)) for x, y in zone["points"]]
        z_id = zone.get("hashId", "")
        name = zone.get("name", "")
        is_charging_area = name == "charging_area"
        is_active = z_id in active_zone_ids

        if is_charging_area:
            color, alpha, stroke_w = _C_CHARGING, "66", "1"
        elif is_active:
            color, alpha, stroke_w = _C_ZONE_ACTIVE, "cc", "2.5"
        else:
            color, alpha, stroke_w = _C_ZONE_IDLE, zone_alphas[i % len(zone_alphas)], "1.5"

        parts.append(
            f'<polygon points="{poly(pts)}" fill="{color}{alpha}" '
            f'stroke="{color}" stroke-width="{stroke_w}"/>'
        )

        if len(pts) >= 2:
            lcx = sum(p[0] for p in pts) / len(pts)
            lcy = sum(p[1] for p in pts) / len(pts)
            label = name if name and name != "charging_area" else (z_id[:6] if z_id else "")
            if label:
                parts.append(
                    f'<text x="{tx(lcx):.1f}" y="{ty(lcy):.1f}" text-anchor="middle" '
                    f'dominant-baseline="middle" font-size="10" font-family="sans-serif" '
                    f'fill="{_C_TEXT}" fill-opacity="0.8">{label}</text>'
                )

    if charging_loc:
        dx = tx(float(charging_loc.get("x", 0)))
        dy = ty(float(charging_loc.get("y", 0)))
        hdg = charging_loc.get("heading", charging_loc.get("theta", 0)) or 0
        parts.append(
            f'<circle cx="{dx:.1f}" cy="{dy:.1f}" r="10" fill="{_C_DOCK}" '
            f'fill-opacity="0.9" stroke="white" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{dx:.1f}" y="{dy:.1f}" text-anchor="middle" dominant-baseline="middle" '
            f'font-size="11" font-family="sans-serif">⚡</text>'
        )
        if hdg:
            ang = float(hdg) if abs(float(hdg)) <= 6.2832 else math.radians(float(hdg))
            ax = dx + 15 * math.sin(ang)
            ay = dy - 15 * math.cos(ang)
            parts.append(
                f'<line x1="{dx:.1f}" y1="{dy:.1f}" x2="{ax:.1f}" y2="{ay:.1f}" '
                f'stroke="{_C_DOCK}" stroke-width="2" stroke-dasharray="3 2"/>'
            )

    if robot_loc:
        rx = tx(float(robot_loc.get("x", 0)))
        ry = ty(float(robot_loc.get("y", 0)))
        heading = robot_loc.get("heading", robot_loc.get("theta", 0)) or 0
        parts.append(
            f'<circle cx="{rx:.1f}" cy="{ry:.1f}" r="9" fill="{_C_ROBOT}" '
            f'stroke="white" stroke-width="2"/>'
        )
        if heading:
            ang = float(heading) if abs(float(heading)) <= 6.2832 else math.radians(float(heading))
            ax = rx + 18 * math.sin(ang)
            ay = ry - 18 * math.cos(ang)
            parts.append(
                f'<line x1="{rx:.1f}" y1="{ry:.1f}" x2="{ax:.1f}" y2="{ay:.1f}" '
                f'stroke="{_C_ROBOT}" stroke-width="3" stroke-linecap="round"/>'
            )

    sc = _STATUS_COLOR.get(work_status, "#374151")
    sl = _STATUS_LABEL.get(work_status, "?")
    parts += [
        f'<rect x="6" y="6" width="90" height="22" rx="5" fill="{sc}" fill-opacity="0.92"/>',
        f'<text x="51" y="20" text-anchor="middle" dominant-baseline="middle" '
        f'font-size="11" font-family="sans-serif" fill="white" font-weight="bold">{sl}</text>',
    ]

    if battery is not None:
        bc = "#4ade80" if battery > 30 else ("#facc15" if battery > 15 else "#f87171")
        parts += [
            '<rect x="104" y="6" width="58" height="22" rx="5" fill="#1f2937" fill-opacity="0.9"/>',
            f'<text x="133" y="20" text-anchor="middle" dominant-baseline="middle" '
            f'font-size="11" font-family="sans-serif" fill="{bc}" font-weight="bold">🔋{battery}%</text>',
        ]

    if rtk_status is not None:
        rl = {0: "RTK ✗", 1: "RTK ~", 2: "RTK ✓", 3: "RTK ✓"}
        rc = {0: "#dc2626", 1: "#d97706", 2: "#16a34a", 3: "#16a34a"}
        parts += [
            f'<rect x="170" y="6" width="54" height="22" rx="5" '
            f'fill="{rc.get(rtk_status, "#374151")}" fill-opacity="0.9"/>',
            f'<text x="197" y="20" text-anchor="middle" dominant-baseline="middle" '
            f'font-size="11" font-family="sans-serif" fill="white" font-weight="bold">'
            f'{rl.get(rtk_status, "RTK ?")}</text>',
        ]

    zcount = (btmap or {}).get("zone_count")
    if zcount:
        parts.append(
            f'<text x="{_CANVAS - 6}" y="{_CANVAS - 8}" text-anchor="end" '
            f'font-size="10" font-family="sans-serif" fill="#6b7280">{zcount} zones</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def _placeholder() -> list[str]:
    return [
        f'<text x="{_CANVAS//2}" y="{_CANVAS//2 - 12}" text-anchor="middle" '
        f'font-size="15" font-family="sans-serif" fill="#4b5563">Map not available</text>',
        f'<text x="{_CANVAS//2}" y="{_CANVAS//2 + 12}" text-anchor="middle" '
        f'font-size="11" font-family="sans-serif" fill="#374151">'
        f'Waiting for MQTT map data or S3 backup map...</text>',
    ]


class LymowRTSPCamera(LymowEntity, Camera):
    """Exposes the robot RTSP stream URL via attributes."""

    _attr_name = "Live Camera"
    _attr_icon = "mdi:cctv"
    _attr_content_type = "image/jpeg"
    _attr_supported_features = CameraEntityFeature(0)

    def __init__(self, coordinator: LymowCoordinator) -> None:
        LymowEntity.__init__(self, coordinator, "rtsp_camera")
        Camera.__init__(self)

    @property
    def available(self) -> bool:
        return bool(_get_robot_ip(self.coordinator.data or {}))

    @property
    def extra_state_attributes(self) -> dict:
        ip = _get_robot_ip(self.coordinator.data or {})
        if not ip:
            return {}
        return {
            "rtsp_url": f"rtsp://{ip}:{RTSP_PORT}/{RTSP_PATH}",
            "robot_ip": ip,
        }

    async def stream_source(self) -> str | None:
        ip = _get_robot_ip(self.coordinator.data or {})
        return f"rtsp://{ip}:{RTSP_PORT}/{RTSP_PATH}" if ip else None
