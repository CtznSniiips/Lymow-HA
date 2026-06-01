"""Lymow state helpers.

This module is the bridge between:
- protobuf messages received from MQTT (`lymow_pb2.PbOutput`);
- dataclasses produced by protocol.parse_zone_catalog();
- the flat compatibility dict used by existing HA entities.

The coordinator owns the dict. These helpers only mutate/derive it.
"""
from __future__ import annotations

from math import cos, hypot, radians
from typing import Any

from .const import DEFAULT_CHANNEL_BUFFER_M

try:
    from .proto import lymow_pb2 as pb
except Exception:  # pragma: no cover - allows standalone linting
    pb = None  # type: ignore


_ACTIVE_TASK_WORK_STATUSES = {2, 8, 9, 14}  # mowing, resume, zone partition, escaping
# Statuses where the mower is out navigating and we should resolve zone/channel.
# Adds Docking (4) so it tracks on the way HOME too — it crosses the same
# corridors returning, which matters for transit automations (e.g. a gate).
_LOCALIZE_STATUSES = _ACTIVE_TASK_WORK_STATUSES | {4}


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
        for src, dst in [
            ("numSatellites", "gnssNumSatellites"),
            ("horizontalAccuracy", "gnssHorizontalAccuracy"),
            ("verticalAccuracy", "gnssVerticalAccuracy"),
            ("positionQuality", "gnssPositionQuality"),
            ("locNodeStatus", "gnssLocNodeStatus"),
        ]:
            if _has_field(li, src):
                state[dst] = getattr(li, src)

    bo = getattr(msg, "baseOutput", None)
    if _has_msg(bo):
        state["baseOutput"] = bo
        if _has_field(bo, "cutHeight"):
            state["cutHeight"] = bo.cutHeight
        twist = getattr(bo, "twist", None)
        if _has_msg(twist):
            if _has_field(twist, "linear"):
                state["twistLinear"] = twist.linear
            if _has_field(twist, "angular"):
                state["twistAngular"] = twist.angular

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
            if "theta" in pose_dict:
                from math import degrees
                state["mowerHeading"] = round((90 - degrees(pose_dict["theta"])) % 360, 1)

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
        rtk_bind = getattr(rc, "rtkBinding", None)
        if rtk_bind is not None:
            locid = getattr(rtk_bind, "rtkLocid", "")
            if locid:
                state["rtkSn"] = locid
            pmode = getattr(rtk_bind, "powerMode", "")
            if pmode:
                state["rtkPowerMode"] = pmode

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

    # taskConfig: check parent ListFields (not ByteSize) because proto3
    # zero values (chargingMode=0) produce ByteSize=0 but are still valid.
    if any(f.name == "taskConfig" for f, _ in msg.ListFields()):
        tc = msg.taskConfig
        state["taskConfig"] = tc
        for src, dst in [
            ("chargingMode", "chargingMode"),
            ("zoneOrder", "zoneOrder"),
            ("rainCleaning", "rainCleaning"),
            ("disableChargingPark", "disableChargingPark"),
        ]:
            state[dst] = getattr(tc, src)

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


_M_PER_DEG_LAT = 111_320.0


def _latlon_to_local_m(lon: float, lat: float, lat0: float) -> tuple[float, float]:
    """Project (lon, lat) degrees to local planar metres about reference lat0.
    Good enough for the sub-100 m distances we test against channel polygons."""
    return (
        lon * _M_PER_DEG_LAT * cos(radians(lat0)),
        lat * _M_PER_DEG_LAT,
    )


def _point_seg_dist_m(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Distance from point P to segment AB (all in metres)."""
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0.0:
        return hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / seg2
    t = max(0.0, min(1.0, t))
    return hypot(px - (ax + t * dx), py - (ay + t * dy))


def _dist_to_polygon_m(mlon: float, mlat: float, poly: list[tuple[float, float]]) -> float:
    """Min distance (metres) from the mower to a polygon's perimeter. `poly` is
    [(lon, lat), ...]; the mower is assumed outside (callers test inside first)."""
    n = len(poly)
    if n < 2:
        return float("inf")
    px, py = _latlon_to_local_m(mlon, mlat, mlat)
    best = float("inf")
    for i in range(n):
        alon, alat = poly[i]
        blon, blat = poly[(i + 1) % n]
        ax, ay = _latlon_to_local_m(alon, alat, mlat)
        bx, by = _latlon_to_local_m(blon, blat, mlat)
        d = _point_seg_dist_m(px, py, ax, ay, bx, by)
        if d < best:
            best = d
    return best


def _zones_from_state(state: dict[str, Any]) -> list[Any]:
    catalog = state.get("zone_catalog")
    zones = getattr(catalog, "zones", None)
    if isinstance(zones, list):
        return zones

    btmap = state.get("btMap") or {}
    zones = btmap.get("zones") if isinstance(btmap, dict) else None
    return zones if isinstance(zones, list) else []


def _localization_active(state: dict[str, Any]) -> bool:
    """Mower is actively positioned. Check BOTH robotStatus and workStatus: the
    mower reliably sets robotStatus (=Mowing) but often leaves workStatus unset,
    which previously made current zone/channel never resolve."""
    return (
        state.get("workStatus") in _LOCALIZE_STATUSES
        or state.get("robotStatus") in _LOCALIZE_STATUSES
    )


def _polygon_latlon(pts: list[Any], ebp: Any) -> list[tuple[float, float]]:
    """Convert ENU-metre polygon points -> [(lon, lat), ...] for WGS84 matching.
    Handles point dicts {x,y}, (x,y) tuples, or objects with .x/.y. Returns []
    if any point can't be converted."""
    out: list[tuple[float, float]] = []
    for p in pts:
        if isinstance(p, dict):
            px, py = p.get("x"), p.get("y")
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            px, py = p[0], p[1]
        else:
            px, py = getattr(p, "x", None), getattr(p, "y", None)
        ll = enu_to_lla(ebp, {"x": px, "y": py})
        if ll is None:
            return []
        out.append((ll[1], ll[0]))  # (lon, lat)
    return out


def derive_current_zone(state: dict[str, Any]) -> str | None:
    """Zone whose polygon contains the mower's live position.

    Matches in WGS84: the mower's GPS (robot_gps_from_state, which falls back to
    the RTK lat/lon if pose x/y are absent) vs each zone polygon converted from
    ENU metres to lat/lon via the map's GPS origin. (The old version matched raw
    pose x/y and gated on workStatus, which never resolved — wrong field + a
    coordinate assumption that didn't hold.)"""
    if not _localization_active(state):
        return None
    mower = robot_gps_from_state(state)
    ebp = get_enu_base_point(state)
    if not mower or ebp is None:
        return None
    mlat, mlon = mower

    for zone in _zones_from_state(state):
        if isinstance(zone, dict):
            pts = zone.get("points") or []
            name = zone.get("name") or zone.get("hashId")
        else:
            pts = getattr(zone, "polygon_points", []) or []
            name = getattr(zone, "name", None) or getattr(zone, "hash_id", None)
        if not pts or len(pts) < 3:
            continue
        poly = _polygon_latlon(pts, ebp)
        if len(poly) >= 3 and point_in_polygon(mlon, mlat, poly):
            return name
    return None


def _channels_from_state(state: dict[str, Any]) -> list[Any]:
    catalog = state.get("zone_catalog")
    chans = getattr(catalog, "channels", None)
    if isinstance(chans, list):
        return chans
    btmap = state.get("btMap") or {}
    chans = btmap.get("channels") if isinstance(btmap, dict) else None
    return chans if isinstance(chans, list) else []


def _zone_name_by_hash(state: dict[str, Any]) -> dict[str, str]:
    """Map zone hashId -> display name, for labelling channels by the zones they link."""
    out: dict[str, str] = {}
    for z in _zones_from_state(state):
        if isinstance(z, dict):
            h = z.get("hashId"); n = z.get("name") or z.get("zoneRename")
        else:
            h = getattr(z, "hash_id", None); n = getattr(z, "name", None)
        if h:
            out[h] = n or h
    return out


def derive_current_channel(state: dict[str, Any]) -> dict[str, Any] | None:
    """Channel whose polygon contains the mower's live pose (active mowing only).

    Returns {label, channel_id, zone1, zone2, is_docking} or None. The label is
    the human-readable link, e.g. "Front Left Main ↔ Backyard" — useful for
    automations that fire on a transition corridor (e.g. opening a gate)."""
    if not _localization_active(state):
        return None
    mower = robot_gps_from_state(state)
    ebp = get_enu_base_point(state)
    if not mower or ebp is None:
        return None
    mlat, mlon = mower

    bm = state.get("channel_buffer_m")
    buffer_m = float(bm) if bm is not None else DEFAULT_CHANNEL_BUFFER_M

    names = _zone_name_by_hash(state)
    best: dict[str, Any] | None = None
    best_dist = float("inf")
    for ch in _channels_from_state(state):
        if isinstance(ch, dict):
            pts = ch.get("points") or []
            hid = ch.get("hashId"); z1 = ch.get("zone1", ""); z2 = ch.get("zone2", "")
            dock = ch.get("isDockingChannel")
        else:
            pts = getattr(ch, "polygon_points", []) or []
            hid = getattr(ch, "hash_id", None)
            z1 = getattr(ch, "zone1", ""); z2 = getattr(ch, "zone2", "")
            dock = getattr(ch, "is_docking_channel", False)

        if not pts or len(pts) < 3:
            continue
        poly = _polygon_latlon(pts, ebp)
        if len(poly) < 3:
            continue

        # Inside the polygon = distance 0. Otherwise accept the channel when the
        # mower is within the buffer of its perimeter (thin/short corridors miss
        # otherwise). When several channels qualify (junctions), the nearest wins.
        if point_in_polygon(mlon, mlat, poly):
            dist = 0.0
        elif buffer_m > 0.0:
            dist = _dist_to_polygon_m(mlon, mlat, poly)
            if dist > buffer_m:
                continue
        else:
            continue

        if dist >= best_dist:
            continue
        n1 = names.get(z1, z1) or ""
        n2 = names.get(z2, z2) or ""
        if dock:
            label = f"Dock ↔ {n1 or n2}".strip()
        elif n1 and n2:
            label = f"{n1} ↔ {n2}"
        else:
            label = f"Channel {hid[:6]}" if hid else "Channel"
        best_dist = dist
        best = {
            "label": label, "channel_id": hid,
            "zone1": n1, "zone2": n2, "is_docking": bool(dock),
            "distance_m": round(dist, 2),
        }
    return best
