"""Lymow camera platform.

Two cameras:
  - LymowMapCamera   : diagnostic PNG rendered with Pillow (executor-safe).
  - LymowRTSPCamera  : live RTSP stream via HA's built-in `stream` component.
                       The camera card in Lovelace will show a live HLS feed
                       as long as the robot IP is reachable from the HA host.
"""
from __future__ import annotations

import io
import logging
import math
from typing import Any

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, F_IP_ADDRESS, F_NET_DETAIL, RTSP_PATH, RTSP_PORT
from .coordinator import LymowCoordinator
from .entity_base import LymowEntity

_LOGGER = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception as exc:
    Image = ImageDraw = ImageFont = None
    _PIL_ERROR = repr(exc)
else:
    _PIL_ERROR = None

W = H = 800
PAD = 40
# All colours as RGBA tuples (image is created in RGBA mode and converted to RGB at save time)
BG          = (17,  24,  39, 255)
GREEN       = (34, 197,  94, 110)
GREEN_LINE  = (134, 239, 172, 230)
WHITE       = (255, 255, 255, 255)
GREY        = (156, 163, 175, 255)
ORANGE      = (249, 115,  22, 255)
YELLOW      = (251, 191,  36, 255)
RED         = (248, 113, 113, 255)
BLACK       = (  0,   0,   0, 255)

FALLBACK_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _get_robot_ip(data: dict) -> str | None:
    return (
        data.get(F_IP_ADDRESS)
        or (data.get(F_NET_DETAIL) or {}).get("wifiIp")
        or data.get("rest_ip_address")
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


# ── Diagnostic map camera ────────────────────────────────────────────────────

class LymowMapCamera(LymowEntity, Camera):
    _attr_name = "Map"
    _attr_icon = "mdi:map"
    _attr_content_type = "image/png"
    _attr_supported_features = CameraEntityFeature(0)

    def __init__(self, coordinator: LymowCoordinator) -> None:
        LymowEntity.__init__(self, coordinator, "map")
        Camera.__init__(self)
        self._render_error: str | None = None
        self._render_debug: dict[str, Any] = {}

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    # ── sync render (always called in executor) ──────────────────

    def _render(self) -> bytes:
        try:
            img, dbg = build_map_png(self.coordinator.data or {})
            self._render_debug = dbg
            self._render_error = None
            return png_bytes(img)
        except Exception as exc:
            self._render_error = f"{type(exc).__name__}: {exc}"
            _LOGGER.exception("Lymow diagnostic map render failed")
            return text_png("Lymow map render failed", self._render_error)

    # ── camera interface ─────────────────────────────────────────

    def camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        # Sync path kept for compatibility; HA rarely calls this directly.
        return self._render()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        # Pillow is CPU-bound + blocking I/O → offload to executor thread.
        return await self.hass.async_add_executor_job(self._render)

    @property
    def extra_state_attributes(self) -> dict:
        d = self.coordinator.data or {}
        btmap = d.get("btMap") or {}
        if not isinstance(btmap, dict):
            btmap = {}

        zones = btmap.get("zones") or []
        nogo_zones = btmap.get("nogoZones") or []
        channels = btmap.get("channels") or []
        _zname = {
            z.get("hashId"): z.get("name") for z in zones if isinstance(z, dict)
        }

        return {
            "render_mode": "diagnostic_png",
            "pil_available": Image is not None,
            "pil_error": _PIL_ERROR,
            "render_error": self._render_error,
            "render_debug": self._render_debug,
            "zone_count": btmap.get("zone_count"),
            "zones_total": len(zones),
            "zones_with_points": sum(1 for z in zones if z.get("points")),
            "drawable_zone_count": sum(
                1 for z in zones if z.get("points") and len(z.get("points") or []) >= 2
            ),
            "first_zone_points_count": len(zones[0].get("points") or []) if zones else 0,
            "channel_count": len(channels),
            "channels_detail": [
                {
                    "from": _zname.get(c.get("zone1")) or c.get("zone1"),
                    "to": _zname.get(c.get("zone2")) or c.get("zone2"),
                    "points": c.get("points_count", len(c.get("points") or [])),
                    "docking": bool(c.get("isDockingChannel")),
                }
                for c in channels
                if isinstance(c, dict)
            ],
            "nogo_zone_count": len(nogo_zones),
            "nogo_zones_with_points": sum(
                1 for z in nogo_zones
                if isinstance(z, dict) and z.get("points")
            ),
            "has_enu_base_point": bool(btmap.get("enuBasePoint") or d.get("enu_base_point")),
        }


# ── RTSP live camera ─────────────────────────────────────────────────────────

class LymowRTSPCamera(LymowEntity, Camera):
    """Live camera via RTSP → HLS transcoding by HA's stream component.

    Once the robot IP is known, the camera card in Lovelace will display
    a live video feed without any extra configuration.  The `stream`
    integration (enabled by default in HA) handles the RTSP→HLS leg.
    """

    _attr_name = "Live Camera"
    _attr_icon = "mdi:cctv"
    _attr_content_type = "image/png"
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, coordinator: LymowCoordinator) -> None:
        LymowEntity.__init__(self, coordinator, "rtsp_camera")
        Camera.__init__(self)

    @property
    def available(self) -> bool:
        return bool(_get_robot_ip(self.coordinator.data or {}))

    def _rtsp_url(self) -> str | None:
        ip = _get_robot_ip(self.coordinator.data or {})
        return f"rtsp://{ip}:{RTSP_PORT}/{RTSP_PATH}" if ip else None

    async def stream_source(self) -> str | None:
        """Return the RTSP URL consumed by HA's stream component."""
        return self._rtsp_url()

    @property
    def extra_state_attributes(self) -> dict:
        url = self._rtsp_url()
        return {"rtsp_url": url} if url else {}

    def camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        # Fallback still image shown before the stream is available.
        return text_png("Lymow Live Camera", self._rtsp_url() or "Waiting for robot IP…")

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return await self.hass.async_add_executor_job(self.camera_image, width, height)


# ── Rendering helpers ────────────────────────────────────────────────────────

def build_map_png(data: dict) -> tuple:
    if Image is None or ImageDraw is None:
        raise RuntimeError(f"Pillow not available: {_PIL_ERROR}")

    # Use RGBA throughout; convert to RGB only when saving.
    img  = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(img, "RGBA")

    btmap    = data.get("btMap") or {}
    zones    = btmap.get("zones") or []
    drawable = [
        z for z in zones
        if z.get("points") and len(z.get("points") or []) >= 2
    ]

    nogo_zones = btmap.get("nogoZones") or []
    drawable_nogo = [
        z for z in nogo_zones
        if z.get("points") and len(z.get("points") or []) >= 3
    ]

    dbg = {
        "zones":        len(zones),
        "drawable":     len(drawable),
        "first_points": len(zones[0].get("points") or []) if zones else 0,
        "channels":     len((btmap.get("channels") or [])),
        "nogo_zones":   len(nogo_zones),
        "drawable_nogo": len(drawable_nogo),
    }

    draw_text(draw, "Lymow Map Diagnostic", 20, 16, 22, WHITE)
    draw_text(
        draw,
        f"zones={len(zones)} drawable={len(drawable)} first_pts={dbg['first_points']}",
        20, 46, 15, GREY,
    )

    if not drawable:
        draw_text(draw, "No drawable polygons in state", 20, 100, 18, RED)
        return img.convert("RGB"), dbg

    all_pts: list[tuple[float, float]] = []
    for z in drawable:
        all_pts.extend(safe_points(z.get("points") or []))

    if not all_pts:
        draw_text(draw, "Drawable zones exist but points failed to parse", 20, 100, 18, RED)
        return img.convert("RGB"), dbg

    min_x = min(x for x, y in all_pts)
    max_x = max(x for x, y in all_pts)
    min_y = min(y for x, y in all_pts)
    max_y = max(y for x, y in all_pts)
    dbg.update({"min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y})

    scale = (W - PAD * 2) / max(max_x - min_x or 1, max_y - min_y or 1)

    def sx(x: float) -> float: return (x - min_x) * scale + PAD
    def sy(y: float) -> float: return H - ((y - min_y) * scale + PAD)

    # Channels / corridors — draw behind zone outlines.
    for channel in (btmap.get("channels") or []):
        pts = safe_points(channel.get("points") or [])
        if len(pts) < 2:
            continue
        if len(pts) > 300:
            step = max(1, math.ceil(len(pts) / 300))
            pts = pts[::step]
        xy = [(sx(x), sy(y)) for x, y in pts]
        if len(xy) >= 3:
            draw.line(xy + [xy[0]], fill=YELLOW, width=2)
        elif len(xy) >= 2:
            draw.line(xy, fill=YELLOW, width=2)

    for idx, zone in enumerate(drawable):
        pts = safe_points(zone.get("points") or [])
        if len(pts) > 300:
            step = max(1, math.ceil(len(pts) / 300))
            pts  = pts[::step]
        xy = [(sx(x), sy(y)) for x, y in pts]
        if len(xy) >= 3:
            draw.polygon(xy, fill=GREEN, outline=GREEN_LINE)
            cx = sum(p[0] for p in xy) / len(xy)
            cy = sum(p[1] for p in xy) / len(xy)
            label = str(zone.get("name") or zone.get("hashId") or idx)[:16]
            draw_center(draw, label, cx, cy, 10, WHITE)
    
    # No-go zones / excluded areas — orange overlay
    for idx, zone in enumerate(drawable_nogo):
        pts = safe_points(zone.get("points") or [])
        if len(pts) < 3:
            continue

        if len(pts) > 300:
            step = max(1, math.ceil(len(pts) / 300))
            pts = pts[::step]

        xy = [(sx(x), sy(y)) for x, y in pts]

        if xy and xy[0] != xy[-1]:
            xy.append(xy[0])

        try:
            draw.polygon(
                xy,
                fill=(249, 115, 22, 130),      # orange transparent
                outline=(251, 146, 60, 240),   # orange border
            )

            cx = sum(p[0] for p in xy) / len(xy)
            cy = sum(p[1] for p in xy) / len(xy)
            label = str(zone.get("name") or zone.get("hashId") or f"No-Go {idx + 1}")[:14]
            draw_center(draw, label, cx, cy, 9, WHITE)

        except Exception:
            pass

    # Mowed Poligons QUERY_PATH
    mowed_polygons = data.get("mowed_area_polygons") or []
    for poly in mowed_polygons:
        pts = safe_points(poly)
        if len(pts) < 3:
            continue

        if len(pts) > 800:
            step = max(1, math.ceil(len(pts) / 800))
            pts = pts[::step]

        xy = [(sx(x), sy(y)) for x, y in pts]

        if xy and xy[0] != xy[-1]:
            xy.append(xy[0])

        draw.polygon(
            xy,
            fill=(59, 130, 246, 90),
            outline=(37, 99, 235, 220),
        )
    dbg.update({
        "mowed_area_polygons": len(mowed_polygons),
        "mowed_area_points": sum(len(safe_points(poly)) for poly in mowed_polygons),
    })     

    dock = data.get("chargingStationLoc")
    if isinstance(dock, dict):
        x, y = to_float(dock.get("x")), to_float(dock.get("y"))
        if x is not None and y is not None:
            dx, dy = sx(x), sy(y)
            draw.ellipse((dx - 10, dy - 10, dx + 10, dy + 10), fill=YELLOW, outline=WHITE, width=2)
            draw_center(draw, "D", dx, dy, 11, BLACK)

    robot = data.get("robotLoc") or data.get("pose") or data.get("robotPosePib")
    if isinstance(robot, dict):
        x, y = to_float(robot.get("x")), to_float(robot.get("y"))
        if x is not None and y is not None:
            rx, ry = sx(x), sy(y)
            draw.ellipse((rx - 9, ry - 9, rx + 9, ry + 9), fill=ORANGE, outline=WHITE, width=2)
            draw_center(draw, "R", rx, ry, 11, WHITE)

    return img.convert("RGB"), dbg


def text_png(title: str, subtitle: str) -> bytes:
    if Image is None or ImageDraw is None:
        return FALLBACK_PNG
    img  = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(img, "RGBA")
    draw_center(draw, title,    W / 2, H / 2 - 16, 22, WHITE)
    draw_center(draw, subtitle, W / 2, H / 2 + 18, 13, GREY)
    return png_bytes(img.convert("RGB"))


def png_bytes(img) -> bytes:
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    return bio.getvalue()


def font(size: int):
    if ImageFont is None:
        return None
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


def draw_text(draw, text: str, x: float, y: float, size: int, fill) -> None:
    draw.text((x, y), str(text), font=font(size), fill=fill)


def draw_center(draw, text: str, x: float, y: float, size: int, fill) -> None:
    f    = font(size)
    text = str(text)
    try:
        box     = draw.textbbox((0, 0), text, font=f)
        tw, th  = box[2] - box[0], box[3] - box[1]
    except Exception:
        tw, th = len(text) * size * 0.6, size
    draw.text((x - tw / 2, y - th / 2), text, font=f, fill=fill)


def to_float(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except Exception:
        return None


def safe_points(points: list[Any]) -> list[tuple[float, float]]:
    """Normalise zone points regardless of storage format.

    Stored as dicts {x, y} from older MQTT path or as tuples (x, y)
    from decode_map_fields / S3 backup map.
    """
    out: list[tuple[float, float]] = []
    for p in points:
        if isinstance(p, dict):
            x, y = to_float(p.get("x")), to_float(p.get("y"))
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            x, y = to_float(p[0]), to_float(p[1])
        else:
            continue
        if x is not None and y is not None:
            out.append((x, y))
    return out