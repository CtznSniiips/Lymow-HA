"""Lymow state helpers.

Pure helpers used by the coordinator, map camera and device trackers.
They work with the flat dict produced by protocol.py, not compiled protobufs.
"""
from __future__ import annotations

from math import cos, radians
from typing import Any

# Active task states where a "current zone" makes sense.
_ACTIVE_TASK_WORK_STATUSES = {2, 8, 9, 14}  # mowing, resume, zone partition, escaping


def _get_float(obj: Any, key: str) -> float | None:
    """Read a float from either a dict or an object attribute."""
    if obj is None:
        return None
    try:
        value = obj.get(key) if isinstance(obj, dict) else getattr(obj, key)
    except Exception:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def enu_to_lla(enu_base_point: Any, pose: Any) -> tuple[float, float] | None:
    """Convert local ENU metres to GPS lat/lon.

    Lymow's live mower position is usually local map/ENU coordinates. The
    real-world anchor is ``PbMap.enuBasePoint`` from QUERY_MAP. This flat-earth
    conversion is sufficiently accurate for lawn-scale distances.
    """
    base_lat = _get_float(enu_base_point, "latitude")
    base_lon = _get_float(enu_base_point, "longitude")
    x = _get_float(pose, "x")  # east in metres
    y = _get_float(pose, "y")  # north in metres
    if base_lat is None or base_lon is None or x is None or y is None:
        return None
    lat = base_lat + (y / 111111.0)
    lon = base_lon + (x / (111111.0 * cos(radians(base_lat))))
    return lat, lon


def get_enu_base_point(state: dict[str, Any]) -> dict[str, Any] | None:
    """Return sticky ENU base point from top-level alias or btMap."""
    ebp = state.get("enu_base_point")
    if isinstance(ebp, dict):
        return ebp
    btmap = state.get("btMap") or {}
    ebp = btmap.get("enuBasePoint") if isinstance(btmap, dict) else None
    return ebp if isinstance(ebp, dict) else None


def get_robot_pose(state: dict[str, Any]) -> dict[str, Any] | None:
    """Return live robot local pose, preferring PbOutput.pose over robotPosePib."""
    for key in ("pose", "robotLoc", "robotPosePib"):
        pose = state.get(key)
        if isinstance(pose, dict) and pose.get("x") is not None and pose.get("y") is not None:
            return pose
    return None


def robot_gps_from_state(state: dict[str, Any]) -> tuple[float, float] | None:
    """Best live GPS position.

    Prefer derived ENU-base + local pose, because robotLlaCoords is schema
    supported but often not emitted. Fallback to REST/cloud robotLocation or
    decoded top-level latitude/longitude.
    """
    derived = enu_to_lla(get_enu_base_point(state), get_robot_pose(state))
    if derived is not None:
        return derived

    loc = state.get("robotLocation")
    if isinstance(loc, (list, tuple)) and len(loc) >= 2:
        try:
            return float(loc[0]), float(loc[1])
        except (TypeError, ValueError):
            pass

    lat = state.get("latitude")
    lon = state.get("longitude")
    if lat is not None and lon is not None:
        try:
            return float(lat), float(lon)
        except (TypeError, ValueError):
            pass
    return None


def polygon_area(polygon: list[tuple[float, float]]) -> float:
    """Compute polygon area in square metres."""
    n = len(polygon)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) * 0.5


def point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test for local map coordinates."""
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            x_intersect = (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
            if x < x_intersect:
                inside = not inside
        j = i
    return inside


def derive_current_zone(state: dict[str, Any]) -> str | None:
    """Derive the zone containing the mower's live local pose.

    Uses the simplified zone polygons decoded into ``btMap.zones[].points``.
    Returns the zone name if available, otherwise the hashId.
    """
    pose = get_robot_pose(state)
    if not pose:
        return None
    work_status = state.get("workStatus")
    if work_status not in _ACTIVE_TASK_WORK_STATUSES:
        return None
    try:
        x = float(pose["x"])
        y = float(pose["y"])
    except (KeyError, TypeError, ValueError):
        return None

    btmap = state.get("btMap") or {}
    zones = btmap.get("zones") if isinstance(btmap, dict) else None
    if not isinstance(zones, list):
        return None

    for zone in zones:
        pts = zone.get("points") if isinstance(zone, dict) else None
        if not pts or len(pts) < 3:
            continue
        try:
            polygon = [(float(px), float(py)) for px, py in pts]
        except Exception:
            continue
        if point_in_polygon(x, y, polygon):
            return zone.get("name") or zone.get("hashId")
    return None
