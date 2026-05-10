"""Lymow camera platform.

Two camera entities:
  1. LymowMapCamera  — SVG map rendered from btMap zone data (MQTT)
  2. LymowRTSPCamera — live video stream via RTSP (requires local network)

Map data source (MQTT / PbBtMap field 23):
  btMap.zones[]:
    hashId  — ID used in zone commands
    name    — human label (e.g. "charging_area")
    points  — simplified boundary [(x, y), ...] in local metres
  chargingStationLoc: {x, y, heading} — dock position in local metres

RTSP URL: rtsp://<ipAddress>:10022/h264ESVideoTest
"""
from __future__ import annotations

import logging
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

_LOGGER = logging.getLogger(__name__)

_CANVAS  = 500
_PADDING = 28

# Colour palette
_C_BG           = "#111827"
_C_LAWN         = "#1a3a1a"
_C_BOUNDARY     = "#4ade80"
_C_ZONE_IDLE    = "#22c55e"
_C_ZONE_ACTIVE  = "#86efac"
_C_CHARGING     = "#f59e0b"
_C_DOCK         = "#fbbf24"
_C_ROBOT        = "#f97316"
_C_TEXT         = "white"

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
     3: "PAUSED",  4: "DOCKING", 5: "CHARGING", 6: "REMOTE",
     7: "ERROR",   8: "RESUMING", 9: "MAPPING", 10: "DOCKING",
    11: "UPDATE",  12: "CHARGED", 13: "E-STOP", 14: "ESCAPING",
}


def _get_robot_ip(data: dict) -> str | None:
    return (
        data.get(F_IP_ADDRESS)
        or (data.get(F_NET_DETAIL) or {}).get("wifiIp")
    )


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
    """SVG map from btMap zone data (received via MQTT PbBtMap)."""

    _attr_name               = "Map"
    _attr_icon               = "mdi:map"
    _attr_content_type       = "image/svg+xml"
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
            robot_loc=d.get("pose") or d.get("robotLoc") or d.get("robotPosePib"),
            work_status=d.get("workStatus", WORK_STATUS_OFFLINE),
            rtk_status=d.get("rtkStatus"),
            battery=d.get("battery"),
        )
        return svg.encode("utf-8")

    @property
    def extra_state_attributes(self) -> dict:
        d = self.coordinator.data or {}
        attrs: dict = {}
        btmap = d.get("btMap") or {}
        if btmap.get("zone_count"):
            attrs["zone_count"] = btmap["zone_count"]
        # Expose zone list for automations / dashboards
        zones = btmap.get("zones", [])
        if zones:
            attrs["zones"] = [
                {"hashId": z.get("hashId"), "name": z.get("name", z.get("hashId", ""))}
                for z in zones if z.get("hashId")
            ]
        if ma := d.get("mapArea"):
            attrs["map_area_m2"] = ma
        if pose := d.get("pose") or d.get("robotLoc") or d.get("robotPosePib"):
            attrs["robot_local_position"] = pose
        if ebp := (btmap.get("enuBasePoint") or d.get("enu_base_point")):
            attrs["enu_base_point"] = ebp
        return attrs


# ── SVG renderer ───────────────────────────────────────────────

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
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {_CANVAS} {_CANVAS}" width="{_CANVAS}" height="{_CANVAS}">',
        f'<rect width="{_CANVAS}" height="{_CANVAS}" fill="{_C_BG}"/>',
    ]

    zones = (btmap or {}).get("zones", [])
    # Only zones that have boundary points
    drawable = [z for z in zones if z.get("points") and len(z["points"]) >= 2]

    if not drawable and not charging_loc:
        parts += _placeholder()
        parts.append("</svg>")
        return "\n".join(parts)

    # ── Compute bounding box ─────────────────────────────────────────────
    all_pts: list[tuple[float, float]] = []
    for z in drawable:
        all_pts.extend(z["points"])
    if charging_loc:
        all_pts.append((charging_loc.get("x", 0), charging_loc.get("y", 0)))
    if robot_loc:
        all_pts.append((robot_loc.get("x", 0), robot_loc.get("y", 0)))

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

    def tx(x: float) -> str: return f"{(x - min_x) * scale + _PADDING:.1f}"
    def ty(y: float) -> str: return f"{(y - min_y) * scale + _PADDING:.1f}"
    def poly(pts: list) -> str: return " ".join(f"{tx(x)},{ty(y)}" for x, y in pts)

    # ── Background lawn fill using all zone points as convex hull approx ─
    if len(all_pts) >= 3:
        # Sort by angle from centroid for a rough convex outline
        cx = sum(p[0] for p in all_pts) / len(all_pts)
        cy = sum(p[1] for p in all_pts) / len(all_pts)
        hull = sorted(all_pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
        parts.append(
            f'<polygon points="{poly(hull)}" '
            f'fill="{_C_LAWN}" stroke="{_C_BOUNDARY}" stroke-width="1.5" stroke-dasharray="4 2"/>'
        )

    # ── Draw zones ───────────────────────────────────────────────────────
    zone_alphas = ["99", "aa", "bb", "99", "88", "aa"]
    for i, zone in enumerate(drawable):
        pts = zone["points"]
        z_id = zone.get("hashId", "")
        name = zone.get("name", "")
        is_charging_area = name == "charging_area"
        is_active = z_id in active_zone_ids

        if is_charging_area:
            color = _C_CHARGING
            alpha = "66"
            stroke_w = "1"
        elif is_active:
            color = _C_ZONE_ACTIVE
            alpha = "cc"
            stroke_w = "2.5"
        else:
            color = _C_ZONE_IDLE
            alpha = zone_alphas[i % len(zone_alphas)]
            stroke_w = "1.5"

        parts.append(
            f'<polygon points="{poly(pts)}" '
            f'fill="{color}{alpha}" stroke="{color}" stroke-width="{stroke_w}"/>'
        )

        # Label — zone name or short hash
        if len(pts) >= 2:
            lcx = sum(p[0] for p in pts) / len(pts)
            lcy = sum(p[1] for p in pts) / len(pts)
            label = name if name and name != "charging_area" else (z_id[:6] if z_id else "")
            if label:
                parts.append(
                    f'<text x="{tx(lcx)}" y="{ty(lcy)}" text-anchor="middle" '
                    f'dominant-baseline="middle" font-size="10" '
                    f'font-family="sans-serif" fill="{_C_TEXT}" '
                    f'fill-opacity="0.8">{label}</text>'
                )

    # ── Draw charging dock ───────────────────────────────────────────────
    if charging_loc:
        dx = float(tx(charging_loc.get("x", 0)))
        dy = float(ty(charging_loc.get("y", 0)))
        hdg = charging_loc.get("heading", 0)
        # Dock circle
        parts.append(
            f'<circle cx="{dx:.1f}" cy="{dy:.1f}" r="10" '
            f'fill="{_C_DOCK}" fill-opacity="0.9" stroke="white" stroke-width="2"/>'
        )
        # Lightning bolt ⚡ symbol
        parts.append(
            f'<text x="{dx:.1f}" y="{dy:.1f}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="11" font-family="sans-serif">⚡</text>'
        )
        # Direction tick
        if hdg:
            ang = math.radians(hdg)
            ax = dx + 15 * math.sin(ang)
            ay = dy - 15 * math.cos(ang)
            parts.append(
                f'<line x1="{dx:.1f}" y1="{dy:.1f}" x2="{ax:.1f}" y2="{ay:.1f}" '
                f'stroke="{_C_DOCK}" stroke-width="2" stroke-dasharray="3 2"/>'
            )


    # ── Draw live robot position ──────────────────────────────────────────
    if robot_loc and robot_loc.get("x") is not None and robot_loc.get("y") is not None:
        rx = float(tx(robot_loc.get("x", 0)))
        ry = float(ty(robot_loc.get("y", 0)))
        heading = robot_loc.get("heading", robot_loc.get("theta", 0)) or 0
        parts.append(
            f'<circle cx="{rx:.1f}" cy="{ry:.1f}" r="9" '
            f'fill="{_C_ROBOT}" stroke="white" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{rx:.1f}" y="{ry + 1:.1f}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="10" font-family="sans-serif" '
            f'fill="white">●</text>'
        )
        if heading:
            # theta/heading is treated as radians when small, degrees otherwise.
            ang = heading if abs(float(heading)) <= 6.2832 else math.radians(float(heading))
            ax = rx + 18 * math.sin(ang)
            ay = ry - 18 * math.cos(ang)
            parts.append(
                f'<line x1="{rx:.1f}" y1="{ry:.1f}" x2="{ax:.1f}" y2="{ay:.1f}" '
                f'stroke="{_C_ROBOT}" stroke-width="3" stroke-linecap="round"/>'
            )

    # ── HUD: status badge ─────────────────────────────────────────────────
    sc = _STATUS_COLOR.get(work_status, "#374151")
    sl = _STATUS_LABEL.get(work_status, "?")
    parts += [
        f'<rect x="6" y="6" width="90" height="22" rx="5" fill="{sc}" fill-opacity="0.92"/>',
        f'<text x="51" y="20" text-anchor="middle" dominant-baseline="middle" '
        f'font-size="11" font-family="sans-serif" fill="white" font-weight="bold">{sl}</text>',
    ]

    # ── HUD: battery ─────────────────────────────────────────────────────
    if battery is not None:
        bc = "#4ade80" if battery > 30 else ("#facc15" if battery > 15 else "#f87171")
        parts += [
            f'<rect x="104" y="6" width="58" height="22" rx="5" fill="#1f2937" fill-opacity="0.9"/>',
            f'<text x="133" y="20" text-anchor="middle" dominant-baseline="middle" '
            f'font-size="11" font-family="sans-serif" fill="{bc}" font-weight="bold">'
            f'🔋{battery}%</text>',
        ]

    # ── HUD: RTK ─────────────────────────────────────────────────────────
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

    # ── Zone count label ──────────────────────────────────────────────────
    zcount = (btmap or {}).get("zone_count")
    if zcount:
        parts.append(
            f'<text x="{_CANVAS - 6}" y="{_CANVAS - 8}" text-anchor="end" '
            f'font-size="10" font-family="sans-serif" fill="#6b7280">'
            f'{zcount} zones</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def _placeholder() -> list[str]:
    return [
        f'<text x="{_CANVAS//2}" y="{_CANVAS//2 - 12}" text-anchor="middle" '
        f'font-size="15" font-family="sans-serif" fill="#4b5563">Map not available</text>',
        f'<text x="{_CANVAS//2}" y="{_CANVAS//2 + 12}" text-anchor="middle" '
        f'font-size="11" font-family="sans-serif" fill="#374151">'
        f'Waiting for MQTT map data (QUERY_MAP)...</text>',
    ]


# ── RTSP camera ────────────────────────────────────────────────

class LymowRTSPCamera(LymowEntity, Camera):
    """Exposes the robot RTSP stream URL via attributes.

    HA cannot pull RTSP natively — use go2rtc or a Generic Camera entity.
    The rtsp_url attribute contains the full URL.
    """

    _attr_name               = "Live Camera"
    _attr_icon               = "mdi:cctv"
    _attr_content_type       = "image/jpeg"
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
            "rtsp_url":  f"rtsp://{ip}:{RTSP_PORT}/{RTSP_PATH}",
            "robot_ip":  ip,
            "rtsp_port": RTSP_PORT,
        }

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return None
