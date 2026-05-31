"""Lymow state helpers.

This module is the bridge between:
- protobuf messages received from MQTT (`lymow_pb2.PbOutput`);
- dataclasses produced by protocol.parse_zone_catalog();
- the flat compatibility dict used by existing HA entities.

The coordinator owns the dict. These helpers only mutate/derive it.
"""
from __future__ import annotations

from math import cos, radians
from typing import Any

try:
    from .proto import lymow_pb2 as pb
except Exception:  # pragma: no cover - allows standalone linting
    pb = None  # type: ignore


_ACTIVE_TASK_WORK_STATUSES = {2, 8, 9, 14}  # mowing, resume, zone partition, escaping


def _has_msg(msg: Any) -> bool:
    return msg is not None and hasattr(msg, "ByteSize") and msg.ByteSize() > 0


def _has_field(msg: Any, field_name: str) -> bool:
    if msg is None:
        return False
    try:
        return msg.HasField(field_name)
    except Exception:
        # Proto3 scalar fields often have no presence. If ListFields includes it,
        # it is definitely present in this packet.
        try:
            return any(f.name == field_name for f, _ in msg.ListFields())
        except Exception:
            return False


def _msg_to_point_dict(msg: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("x", "y", "z", "theta"):
        if hasattr(msg, key):
            try:
                out[key] = float(getattr(msg, key))
            except Exception:
                pass
    if "theta" in out:
        out["heading"] = out["theta"]
    return out


def _msg_to_lla_dict(msg: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("latitude", "longitude", "altitude"):
        if hasattr(msg, key):
            try:
                out[key] = float(getattr(msg, key))
            except Exception:
                pass
    return out


def _msg_to_tz_dict(msg: Any) -> dict[str, int]:
    return {
        "hour": int(getattr(msg, "hour", 0) or 0),
        "minute": int(getattr(msg, "minute", 0) or 0),
    }


def merge_pboutput(state: dict[str, Any], msg: Any) -> dict[str, Any]:
    """Merge one PbOutput into the flat coordinator state.

    PbOutput messages are partial. This function updates only the fields that
    are present in the current packet and intentionally preserves sticky fields
    such as zone_catalog / btMap / enu_base_point.
    """
    if msg is None:
        return state

    # Keep original protobuf submessages for advanced consumers.
    for field, value in msg.ListFields():
        if field.name == "btMap":
            continue

        state[field.name] = value

    if getattr(msg, "msgId", None):
        state["msgId"] = msg.msgId
    if getattr(msg, "version", None):
        state["version"] = msg.version

    # Repeated scalar fields. errorCodes/warningCodes are repeated, so proto3
    # omits them when empty — without an explicit clear they'd stay stuck at the
    # last error after it resolved. robotInfo is a full status snapshot, so clear
    # them when a robotInfo frame arrives carrying none (except in the Error (7)
    # / Emergency-Stop (13) states, where the active error is legitimate).
    ri = getattr(msg, "robotInfo", None)
    _ri_present = _has_msg(ri)
    _ws = getattr(ri, "workStatus", None) if _ri_present else None
    if len(getattr(msg, "errorCodes", [])):
        state["errorCodes"] = list(msg.errorCodes)
        state["errorCode"] = msg.errorCodes[0]
    elif _ri_present and _ws not in (7, 13):
        state["errorCodes"] = []
        state["errorCode"] = 0
    if len(getattr(msg, "warningCodes", [])):
        state["warningCodes"] = list(msg.warningCodes)
    elif _ri_present:
        state["warningCodes"] = []

    if _has_msg(ri):
        state["robotInfo"] = ri
        for src, dst in [
            ("robotStatus", "robotStatus"),
            ("battery", "battery"),
            ("wifiSignalQuality", "wifiSignalQuality"),
            ("lteSignalQuality", "lteSignalQuality"),
            ("btSignalQuality", "btSignalQuality"),
            ("workStatus", "workStatus"),
        ]:
            if _has_field(ri, src):
                state[dst] = getattr(ri, src)
        # proto3 bools are omitted from the wire when false, so the _has_field
        # gate above would leave them stuck at their last true value (e.g.
        # Charging never turning off after the mower leaves the dock). robotInfo
        # is a full status snapshot, so read these directly — false then applies.
        for b in ("isRecharging", "isCharging", "wifiWorking", "lteWorking"):
            state[b] = bool(getattr(ri, b, False))
        if "workStatus" in state:
            state["isOnline"] = True

    li = getattr(msg, "localizationInfo", None)
    if _has_msg(li):
        state["localizationInfo"] = li

    bo = getattr(msg, "baseOutput", None)
    if _has_msg(bo):
        state["baseOutput"] = bo
        if _has_field(bo, "cutHeight"):
            state["cutHeight"] = bo.cutHeight

    dp = getattr(msg, "deviceInfo", None)
    if _has_msg(dp):
        state["deviceInfo"] = dp
        for src, dst in [
            ("fwVersion", "fwVersion"),
            ("mcuVersion", "appFwVersion"),
            ("softwareVersion", "mcuVersion"),
            ("softwareVersion", "softwareVersion"),
            ("wifiSsid", "wifiSsid"),
            ("ipAddress", "ipAddress"),
            ("macAddress", "macAddress"),
            ("sn", "sn"),
            ("rtkSn", "rtkSn"),
            ("simId", "simId"),
            ("wheelVer", "wheelVer"),
            ("knifeVer", "knifeVer"),
        ]:
            if _has_field(dp, src):
                val = getattr(dp, src)
                state[dst] = val.strip() if isinstance(val, str) else val

    ci = getattr(msg, "cleanInfo", None)
    if _has_msg(ci):
        state["cleanInfo"] = ci
        for src, dst in [
            ("cleanTime", "cleanTime"),
            ("cleanArea", "cleanArea"),
            ("remainCleanTime", "remainCleanTime"),
            ("cleanPercent", "cleanPercent"),
            ("mapArea", "mapArea"),
        ]:
            if _has_field(ci, src):
                state[dst] = getattr(ci, src)
        if _has_msg(getattr(ci, "areaInfo", None)):
            area = ci.areaInfo
            if len(getattr(area, "cleanZoneIds", [])):
                state["cleanZoneIds"] = list(area.cleanZoneIds)

    pose = getattr(msg, "pose", None)
    if _has_msg(pose):
        state["poseMessage"] = pose
        pose_dict = _msg_to_point_dict(pose)
        if pose_dict:
            state["pose"] = pose_dict

    lla = getattr(msg, "robotLlaCoords", None)
    if _has_msg(lla):
        state["robotLlaCoordsMessage"] = lla
        lla_dict = _msg_to_lla_dict(lla)
        if lla_dict:
            state["robotLlaCoords"] = lla_dict
            state["latitude"] = lla_dict.get("latitude")
            state["longitude"] = lla_dict.get("longitude")

    dock = getattr(msg, "chargingStationLoc", None)
    if _has_msg(dock):
        dock_dict = _msg_to_point_dict(dock)
        if dock_dict:
            state["chargingStationLoc"] = dock_dict

    rc = getattr(msg, "robotConfig", None)
    if _has_msg(rc):
        state["robotConfig"] = rc
        for src, dst in [
            ("rcCutSpeed", "rcCutSpeed"),
            ("rcCutHeight", "rcCutHeight"),
            ("audioVolume", "audioVolume"),
            ("signal", "signal"),
            ("camLedStatus", "camLedStatus"),
            ("vehLedStatus", "vehLedStatus"),
            ("resumeBat", "resumeBat"),
            ("scheduleId", "scheduleId"),
            ("schedulePathOffset", "schedulePathOffset"),
            ("timezoneOffset", "timezoneOffset"),
            ("dockOnError", "dockOnError"),
        ]:
            if _has_field(rc, src):
                state[dst] = getattr(rc, src)
        rr = getattr(rc, "rrConfig", None)
        if _has_msg(rr):
            state["rrConfig"] = rr
            if _has_field(rr, "enableRr"):
                state["rrEnabled"] = bool(rr.enableRr)
            if _has_field(rr, "rechargeBat"):
                state["rrRechargeBat"] = rr.rechargeBat
            if _has_field(rr, "resumeBat"):
                state["rrResumeBat"] = rr.resumeBat
            if _has_msg(getattr(rr, "resumePeriodStart", None)):
                state["rrResumePeriodStart"] = _msg_to_tz_dict(rr.resumePeriodStart)
            if _has_msg(getattr(rr, "resumePeriodEnd", None)):
                state["rrResumePeriodEnd"] = _msg_to_tz_dict(rr.resumePeriodEnd)

    wf = getattr(msg, "wifiConfigRes", None)
    if _has_msg(wf):
        state["wifiConfigRes"] = wf
        if _has_field(wf, "wifiRssi"):
            state["wifiRssi"] = wf.wifiRssi

    net = getattr(msg, "netDetailInfo", None)
    if _has_msg(net):
        state["netDetailInfo"] = net
        for key in [
            "currentNet", "wifiName", "wifiIp", "wifiSignal",
            "simCardStatus", "simIp", "simSignal", "simRegistration",
            "simConnection", "simIccid",
        ]:
            if _has_field(net, key):
                state[key] = getattr(net, key)

    rtk1 = getattr(msg, "rtkDiagnosticL1", None)
    if _has_msg(rtk1):
        state["rtkDiagnosticL1"] = rtk1
        if _has_field(rtk1, "rtkStatus"):
            state["rtkStatus"] = rtk1.rtkStatus

    rtk2 = getattr(msg, "rtkDiagnosticL2", None)
    if _has_msg(rtk2):
        state["rtkDiagnosticL2"] = rtk2

    cr = getattr(msg, "cleanReport", None)
    if _has_msg(cr):
        state["lastCleanReport"] = cr

    return state


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
    """Convert local ENU metres to GPS lat/lon."""
    base_lat = _get_float(enu_base_point, "latitude")
    base_lon = _get_float(enu_base_point, "longitude")
    x = _get_float(pose, "x")  # east in metres
    y = _get_float(pose, "y")  # north in metres
    if base_lat is None or base_lon is None or x is None or y is None:
        return None
    lat = base_lat + (y / 111111.0)
    lon = base_lon + (x / (111111.0 * cos(radians(base_lat))))
    return lat, lon


def get_enu_base_point(state: dict[str, Any]) -> Any | None:
    ebp = state.get("enu_base_point")
    if ebp is not None:
        return ebp
    catalog = state.get("zone_catalog")
    ebp = getattr(catalog, "enu_base_point", None)
    if ebp is not None:
        return ebp
    btmap = state.get("btMap") or {}
    ebp = btmap.get("enuBasePoint") if isinstance(btmap, dict) else None
    return ebp


def get_robot_pose(state: dict[str, Any]) -> Any | None:
    for key in ("pose", "robotLoc", "robotPosePib"):
        pose = state.get(key)
        if pose is None:
            continue
        if isinstance(pose, dict):
            if pose.get("x") is not None and pose.get("y") is not None:
                return pose
        elif getattr(pose, "x", None) is not None and getattr(pose, "y", None) is not None:
            return pose
    return None


def robot_gps_from_state(state: dict[str, Any]) -> tuple[float, float] | None:
    derived = enu_to_lla(get_enu_base_point(state), get_robot_pose(state))
    if derived is not None:
        return derived

    loc = state.get("robotLocation")
    if isinstance(loc, (list, tuple)) and len(loc) >= 2:
        try:
            return float(loc[0]), float(loc[1])
        except (TypeError, ValueError):
            pass

    lla = state.get("robotLlaCoords")
    if isinstance(lla, dict):
        lat = lla.get("latitude")
        lon = lla.get("longitude")
        if lat is not None and lon is not None:
            try:
                return float(lat), float(lon)
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


def _zones_from_state(state: dict[str, Any]) -> list[Any]:
    catalog = state.get("zone_catalog")
    zones = getattr(catalog, "zones", None)
    if isinstance(zones, list):
        return zones

    btmap = state.get("btMap") or {}
    zones = btmap.get("zones") if isinstance(btmap, dict) else None
    return zones if isinstance(zones, list) else []


def derive_current_zone(state: dict[str, Any]) -> str | None:
    """Derive the zone containing the mower's live local pose."""
    pose = get_robot_pose(state)
    if not pose:
        return None
    work_status = state.get("workStatus")
    if work_status not in _ACTIVE_TASK_WORK_STATUSES:
        return None

    x = _get_float(pose, "x")
    y = _get_float(pose, "y")
    if x is None or y is None:
        return None

    for zone in _zones_from_state(state):
        if isinstance(zone, dict):
            pts = zone.get("points") or []
            name = zone.get("name") or zone.get("hashId")
        else:
            pts = getattr(zone, "polygon_points", []) or []
            name = getattr(zone, "name", None) or getattr(zone, "hash_id", None)

        if not pts or len(pts) < 3:
            continue
        try:
            polygon = [(float(px), float(py)) for px, py in pts]
        except Exception:
            continue
        if point_in_polygon(x, y, polygon):
            return name
    return None
