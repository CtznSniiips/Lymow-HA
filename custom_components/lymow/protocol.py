"""Lymow protobuf encode/decode — raw bytes, no compiled pb2 required.

Field numbers confirmed from decompiled.js encoders + live wire captures.

PbOutput root field map (see full docstring in decode_pboutput).
"""
from __future__ import annotations

import base64
import json
import struct
from typing import Any

PB_VERSION_4_9 = 40

USER_CTRL_CLEAN                  = 1
USER_CTRL_DOCK                   = 2
USER_CTRL_PAUSE                  = 3
USER_CTRL_RESUME                 = 4
USER_CTRL_QUERY_MAP              = 19
USER_CTRL_QUERY_SCHEDULES        = 20
USER_CTRL_PAUSE_DOCK             = 21
USER_CTRL_RESUME_DOCK            = 22
USER_CTRL_QUERY_PATH             = 23
USER_CTRL_QUERY_CLEANING         = 24
USER_CTRL_FORCE_REINIT           = 28
USER_CTRL_RECHARGE_DOCK          = 33
USER_CTRL_QUERY_CLEANING_SUMMARY = 34
USER_CTRL_QUERY_ROBOT_CFG        = 35
USER_CTRL_QUERY_WIFI_4G          = 52
USER_CTRL_QUERY_NET_DETAIL       = 53
USER_CTRL_QUERY_RTK_L1           = 57
USER_CTRL_QUERY_RTK_L2           = 58

CLEAN_MODE_INT = {
    0: "NONE",
    1: "ZIGZAG_MODE",
    2: "CHESS_BOARD_MODE",
    3: "PERIMETER_LAPS_ONLY_MODE",
    4: "ADAPTIVE_ZIGZAG_MODE",
}


# ── Wire encoder ───────────────────────────────────────────────

def _enc_varint(value: int) -> bytes:
    if value < 0:
        value &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        out.append(b | 0x80 if value else b)
        if not value:
            return bytes(out)

def _enc_i32(field_no: int, value: int) -> bytes:
    return _enc_varint((field_no << 3) | 0) + _enc_varint(value)

def _enc_bool(field_no: int, value: bool = True) -> bytes:
    return _enc_i32(field_no, 1 if value else 0)

def _enc_len(field_no: int, data: bytes) -> bytes:
    return _enc_varint((field_no << 3) | 2) + _enc_varint(len(data)) + data


# ── PbInput encoders ───────────────────────────────────────────

def encode_userctrl(user_ctrl: int) -> bytes:
    """PbInput {version=40, userCtrl=N}."""
    return _enc_i32(2, PB_VERSION_4_9) + _enc_i32(5, user_ctrl)


def encode_query_map(query_index: int = 0) -> bytes:
    """Query full map via PbInput.btMap.queryMap."""
    btmap = _enc_i32(1, query_index) + _enc_i32(4, 1)
    return (
        _enc_i32(2, PB_VERSION_4_9)
        + _enc_i32(5, USER_CTRL_QUERY_MAP)
        + _enc_len(23, btmap)
    )


def encode_query_path(query_index: int = 0) -> bytes:
    """Query path data via PbInput.btMap.queryPath."""
    btmap = _enc_i32(1, query_index) + _enc_i32(3, 1)
    return (
        _enc_i32(2, PB_VERSION_4_9)
        + _enc_i32(5, USER_CTRL_QUERY_PATH)
        + _enc_len(23, btmap)
    )


def encode_query_schedules() -> bytes:
    return encode_userctrl(USER_CTRL_QUERY_SCHEDULES)


def encode_query_cleaning_info() -> bytes:
    return encode_userctrl(USER_CTRL_QUERY_CLEANING)


def encode_query_cleaning_summary() -> bytes:
    return encode_userctrl(USER_CTRL_QUERY_CLEANING_SUMMARY)


def encode_query_robot_config() -> bytes:
    return encode_userctrl(USER_CTRL_QUERY_ROBOT_CFG)


def encode_query_wifi_4g() -> bytes:
    return encode_userctrl(USER_CTRL_QUERY_WIFI_4G)


def encode_query_net_detail() -> bytes:
    return encode_userctrl(USER_CTRL_QUERY_NET_DETAIL)


def encode_query_rtk_l1() -> bytes:
    return encode_userctrl(USER_CTRL_QUERY_RTK_L1)


def encode_query_rtk_l2() -> bytes:
    return encode_userctrl(USER_CTRL_QUERY_RTK_L2)


def encode_debug_setting(
    *,
    upload_log: bool = False,
    upload_version: bool = False,
    query_wifi_config: bool = False,
    upload_robot_config: bool = False,
    upload_task_config: bool = False,
    exec_cmd: str | None = None,
) -> bytes:
    """Encode PbInput.debugSetting.

    PbInput.debugSetting = field 9. Known PbDebugSetting fields:
      1  uploadLog
      2  uploadVersion
      5  queryWifiConfig
      10 uploadRobotConfig
      11 uploadTaskConfig
      12 execCmd

    The official app appears to use these debug flags to make the robot
    publish PbDeviceProfile/PbWifiConfig-like data such as local IP, firmware,
    MAC and serial number.
    """
    dbg = b""
    if upload_log:
        dbg += _enc_bool(1, True)
    if upload_version:
        dbg += _enc_bool(2, True)
    if query_wifi_config:
        dbg += _enc_bool(5, True)
    if upload_robot_config:
        dbg += _enc_bool(10, True)
    if upload_task_config:
        dbg += _enc_bool(11, True)
    if exec_cmd:
        dbg += _enc_len(12, exec_cmd.encode("utf-8"))

    return _enc_i32(2, PB_VERSION_4_9) + _enc_len(9, dbg)


def encode_query_device_profile() -> bytes:
    """Ask the robot to upload firmware/device profile details."""
    return encode_debug_setting(upload_version=True, upload_robot_config=True)


def encode_query_wifi_config_debug() -> bytes:
    """Ask the robot to upload WiFi config/status details."""
    return encode_debug_setting(query_wifi_config=True)


def encode_app_connect(client_uuid: str) -> bytes:
    """Encode app-connect presence packet.

    PbInput.appConnect = field 7, PbInput.uuid = field 27.
    This mimics the official app announcing an active client session.
    """
    return (
        _enc_i32(2, PB_VERSION_4_9)
        + _enc_i32(7, 1)
        + _enc_len(27, client_uuid.encode("utf-8"))
    )


def encode_start_zones(zone_hash_ids: list[str]) -> bytes:
    """Start mowing selected zones using PbInput.map.goZones."""
    pb = _enc_i32(2, PB_VERSION_4_9) + _enc_i32(5, USER_CTRL_CLEAN)
    map_pb = b""

    for i, hash_id in enumerate(zone_hash_ids, start=1):
        if not hash_id:
            continue
        basic_info = _enc_len(3, hash_id.encode("utf-8")) + _enc_i32(8, i)
        zone = _enc_len(1, basic_info)
        map_pb += _enc_len(1, zone)

    if map_pb:
        pb += _enc_len(12, map_pb)
    return pb


def build_initial_query_packets(
    query_index: int = 0,
    client_uuid: str | None = None,
) -> list[bytes]:
    """Queries to send after MQTT subscribe/reconnect.

    Includes the normal userCtrl queries plus appConnect/debugSetting packets.
    The latter are important because firmware, local IP, MAC and SN may only
    be published when the robot thinks an app client is connected.
    """
    packets: list[bytes] = []

    if client_uuid:
        packets.append(encode_app_connect(client_uuid))

    packets.extend([
        encode_query_device_profile(),
        encode_query_wifi_config_debug(),
        encode_query_map(query_index),
        encode_query_path(query_index),
        encode_query_schedules(),
        encode_query_cleaning_info(),
        encode_query_cleaning_summary(),
        encode_query_net_detail(),
        encode_query_robot_config(),
        encode_query_wifi_4g(),
        encode_query_rtk_l1(),
        encode_query_rtk_l2(),
    ])
    return packets


def build_refresh_query_packets(client_uuid: str | None = None) -> list[bytes]:
    """Periodic refresh for app-only data such as local IP, firmware and signal info."""
    packets: list[bytes] = []

    if client_uuid:
        packets.append(encode_app_connect(client_uuid))

    packets.extend([
        encode_query_device_profile(),
        encode_query_wifi_config_debug(),
        encode_query_cleaning_info(),
        encode_query_net_detail(),
        encode_query_robot_config(),
        encode_query_wifi_4g(),
        encode_query_rtk_l1(),
        encode_query_rtk_l2(),
    ])
    return packets


# ── Envelope ───────────────────────────────────────────────────

def wrap_envelope(raw: bytes) -> str:
    return json.dumps({"message": base64.b64encode(raw).decode("ascii")})

def unwrap_envelope(envelope_bytes: bytes) -> bytes | None:
    try:
        obj = json.loads(envelope_bytes.decode("utf-8"))
        for key in ("message", "value", "data", "payload"):
            v = obj.get(key)
            if isinstance(v, str):
                return base64.b64decode(v)
    except Exception:
        pass
    try:
        return base64.b64decode(envelope_bytes, validate=True)
    except Exception:
        return None


# ── Wire decoder ───────────────────────────────────────────────

def _dec_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    for _ in range(10):
        if pos >= len(buf):
            raise ValueError("truncated varint")
        b = buf[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
    raise ValueError("varint overflow")

def _wire_parse(buf: bytes) -> dict[int, list]:
    if not isinstance(buf, (bytes, bytearray)) or not buf:
        return {}
    out: dict[int, list] = {}
    pos = 0
    while pos < len(buf):
        try:
            tag, pos = _dec_varint(buf, pos)
        except Exception:
            break
        fno, wt = tag >> 3, tag & 7
        try:
            if wt == 0:
                v, pos = _dec_varint(buf, pos)
                out.setdefault(fno, []).append(("v", v))
            elif wt == 1:
                out.setdefault(fno, []).append(("f64", buf[pos:pos+8])); pos += 8
            elif wt == 2:
                ln, pos = _dec_varint(buf, pos)
                out.setdefault(fno, []).append(("L", buf[pos:pos+ln])); pos += ln
            elif wt == 5:
                out.setdefault(fno, []).append(("f32", buf[pos:pos+4])); pos += 4
            else:
                break
        except Exception:
            break
    return out

def _gv(f: dict, n: int) -> int | None:
    e = f.get(n)
    return e[0][1] if e and e[0][0] == "v" else None

def _gs(f: dict, n: int) -> str | None:
    e = f.get(n)
    if e and e[0][0] == "L":
        try: return e[0][1].decode("utf-8")
        except: pass
    return None

def _gf(f: dict, n: int) -> float | None:
    e = f.get(n)
    if e and e[0][0] == "f32" and len(e[0][1]) == 4:
        return round(struct.unpack("<f", e[0][1])[0], 4)
    return None

def _sub(f: dict, n: int) -> dict:
    e = f.get(n)
    return _wire_parse(e[0][1]) if e and e[0][0] == "L" else {}

def _s32(v: int) -> int:
    return v - (1 << 64) if v >= (1 << 31) else v

def _packed_ints(fields: dict, fno: int) -> list[int]:
    result: list[int] = []
    for kind, val in fields.get(fno, []):
        if kind == "v":
            result.append(val)
        elif kind == "L" and isinstance(val, (bytes, bytearray)):
            p = 0
            while p < len(val):
                try:
                    v, p = _dec_varint(val, p)
                    result.append(v)
                except Exception:
                    break
    return result


# ── Small typed decoders ───────────────────────────────────────

def _decode_point(fields: dict) -> dict[str, Any]:
    """Decode PbPoint {x=1 float, y=2 float}."""
    out: dict[str, Any] = {}
    x = _gf(fields, 1)
    y = _gf(fields, 2)
    if x is not None:
        out["x"] = x
    if y is not None:
        out["y"] = y
    return out


def _decode_pose(fields: dict) -> dict[str, Any]:
    """Decode PbPose {x=1, y=2, theta=3, z=4}, all float32.

    For UI compatibility we expose both ``theta`` and ``heading``.
    """
    out = _decode_point(fields)
    theta = _gf(fields, 3)
    z = _gf(fields, 4)
    if theta is not None:
        out["theta"] = theta
        out["heading"] = theta
    if z is not None:
        out["z"] = z
    return out


def _decode_lla(fields: dict) -> dict[str, Any]:
    """Decode PbRobotLLACoords {latitude=1, longitude=2, altitude=3}, all float32."""
    out: dict[str, Any] = {}
    lat = _gf(fields, 1)
    lon = _gf(fields, 2)
    alt = _gf(fields, 3)
    if lat is not None:
        out["latitude"] = lat
    if lon is not None:
        out["longitude"] = lon
    if alt is not None:
        out["altitude"] = alt
    return out


# ── PbBtMap decoder ────────────────────────────────────────────

def decode_btmap(raw: bytes) -> dict[str, Any]:
    """Decode PbBtMap (field 23) — extract zone list with hashIds and names.

    Zone summary (field 3 of zone container):
        field 1 = hashId  (8-char string) — used in encode_start_zones()
        field 2 = mapId   (8-char string)
        field 3 = name    (string) for special zones, or type (varint=0) for regular
        field 5 = simplified boundary points
    """
    zones: list[dict] = []
    zone_count = 0
    enu_base_point: dict[str, Any] | None = None
    root = _wire_parse(raw)

    for kind, map_val in root.get(2, []):
        if kind != "L":
            continue
        map_data = _wire_parse(map_val)

        # PbMap.enuBasePoint = field 7 (real-world origin for local ENU metres)
        enu = _sub(map_data, 7)
        if enu:
            decoded_enu = _decode_lla(enu)
            if decoded_enu:
                enu_base_point = decoded_enu
        for kind2, zc_val in map_data.get(3, []):
            if kind2 != "L":
                continue
            zc = _wire_parse(zc_val)
            # Count full zone blocks
            for kind3, zb_val in zc.get(1, []):
                if kind3 == "L":
                    zone_count += len(_wire_parse(zb_val).get(1, []))
            # Parse zone summaries
            for kind3, zs_val in zc.get(3, []):
                if kind3 != "L":
                    continue
                zs = _wire_parse(zs_val)
                zone: dict[str, Any] = {}
                h = _gs(zs, 1)
                m = _gs(zs, 2)
                if h: zone["hashId"] = h
                if m: zone["mapId"]  = m
                for k3, v3 in zs.get(3, []):
                    if k3 == "L":
                        try: zone["name"] = v3.decode("utf-8")
                        except: pass
                    elif k3 == "v":
                        zone["zoneType"] = v3
                # field 5 = simplified boundary points (repeated PbPoint sub-messages)
                pts: list[tuple[float, float]] = []
                for k5, v5 in zs.get(5, []):
                    if k5 != "L":
                        continue
                    # Each point is a sub-message: field 1 (wire 5) = x, field 2 (wire 5) = y
                    pb = _wire_parse(v5)
                    px = _gf(pb, 1)
                    py = _gf(pb, 2)
                    if px is not None and py is not None:
                        pts.append((round(px, 3), round(py, 3)))
                if pts:
                    zone["points"] = pts
                zones.append(zone)

    out: dict[str, Any] = {"zones": zones, "zone_count": zone_count or len(zones)}
    if enu_base_point:
        out["enuBasePoint"] = enu_base_point
    return out


def _decode_polygon(fields: dict) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for kind, val in fields.get(1, []):
        if kind != "L":
            continue
        pt = _wire_parse(val)
        x = _gf(pt, 1)
        y = _gf(pt, 2)
        if x is not None and y is not None:
            pts.append((round(x, 3), round(y, 3)))
    return pts


def _decode_zone_config(fields: dict) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    for fno, key in [
        (1,"cutHeight"),(5,"brushSpeed"),(6,"cutSpeed"),(7,"cleanMode"),
        (8,"cleanDir"),(9,"pathSpacing"),(10,"perimeterMowLaps"),
        (11,"perimeterMowDir"),(12,"noGoMowLaps"),(13,"obsDecMode"),
        (15,"startProgress"),(16,"relativeCleanDir"),(19,"followDetectMode"),
    ]:
        v = _gv(fields, fno)
        if v is not None:
            cfg[key] = v
    for fno, key in [
        (2,"raiseCutHeight"),(3,"lowerCutHeight"),(14,"pathOrder"),
        (17,"lineFollowMode"),(18,"disableOuterDischarge"),
    ]:
        v = _gv(fields, fno)
        if v is not None:
            cfg[key] = bool(v)
    f = _gf(fields, 4)
    if f is not None:
        cfg["moveSpeed"] = f
    return cfg


def decode_map_fields(map_data: dict) -> dict[str, Any]:
    """Decode a direct PbMap message (PbOutput.map field 11)."""
    zones: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []
    out: dict[str, Any] = {}

    enu = _sub(map_data, 7)
    if enu:
        ebp = _decode_lla(enu)
        if ebp:
            out["enuBasePoint"] = ebp

    dock = _sub(map_data, 4)
    if dock:
        dp = _decode_pose(dock)
        if dp:
            out["chargingStationLoc"] = dp

    for kind, zval in map_data.get(1, []):
        if kind != "L":
            continue
        z = _wire_parse(zval)
        basic = _sub(z, 1)
        zone: dict[str, Any] = {}
        if basic:
            if (v := _gv(basic, 1)) is not None:
                zone["zoneType"] = v
            if (name := _gs(basic, 2)):
                zone["name"] = name
            if (hid := _gs(basic, 3)):
                zone["hashId"] = hid
            if (v := _gv(basic, 4)) is not None:
                zone["isEnabled"] = bool(v)
            poly = _sub(basic, 5)
            if poly:
                pts = _decode_polygon(poly)
                if pts:
                    zone["points"] = pts
                    zone["area"] = round(_polygon_area(pts), 3)
            if (rename := _gs(basic, 6)):
                zone["zoneRename"] = rename
            if (v := _gv(basic, 8)) is not None:
                zone["mowOrder"] = v
        zcfg = _sub(z, 2)
        if zcfg:
            cfg = _decode_zone_config(zcfg)
            if cfg:
                zone["zoneConfig"] = cfg
        if zone:
            zones.append(zone)

    for kind, cval in map_data.get(3, []):
        if kind != "L":
            continue
        chf = _wire_parse(cval)
        ch: dict[str, Any] = {}
        for fno, key in [(1,"hashId"),(2,"zone1"),(3,"zone2")]:
            if (v := _gs(chf, fno)):
                ch[key] = v
        for fno, key in [(4,"isValid"),(6,"isDockingChannel")]:
            if (v := _gv(chf, fno)) is not None:
                ch[key] = bool(v)
        poly = _sub(chf, 5)
        if poly:
            pts = _decode_polygon(poly)
            if pts:
                ch["points"] = pts
        if ch:
            channels.append(ch)

    if zones:
        out["zones"] = zones
        out["zone_count"] = len(zones)
    if channels:
        out["channels"] = channels
    return out




def decode_pbmap(raw: bytes) -> dict[str, Any]:
    """Decode a standalone PbMap file downloaded from S3 backup maps.

    Backup map files such as ``device_xxx/map/map.pb`` are not PbOutput
    envelopes and are not PbBtMap wrappers: they are direct PbMap messages.
    """
    if not raw:
        return {}
    return decode_map_fields(_wire_parse(raw))


def _polygon_area(pts: list[tuple[float, float]]) -> float:
    if len(pts) < 3:
        return 0.0
    total = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        total += x1 * y2 - x2 * y1
    return abs(total) * 0.5


# ── PbOutput decoder ───────────────────────────────────────────

def decode_pboutput(raw: bytes) -> dict[str, Any]:
    """Parse raw PbOutput bytes into a flat state dict.

    Field mapping (confirmed from decompiled.js + live wire):

    Root:
      1  msgId             int32
      2  version           int32
      3  errorCodes        packed int32
      4  warningCodes      packed int32
      5  PbRobotInfo       FLAT (no nested PbRobotStatus):
             1 robotStatus       int32 (signed)
             2 battery           int32  0-100%
             3 wifiSignalQuality int32  dBm signed
             4 lteSignalQuality  int32  dBm signed
             5 btSignalQuality   int32  dBm signed
             6 workStatus        int32
             7 isRecharging      bool
             8 isCharging        bool
             9 wifiWorking       bool
            10 lteWorking        bool
      6  PbLocalizationInfo  (RTK fallback when field 35 absent)
      9  PbDebugSetting      (mostly 0 — ignored)
     10  PbDeviceProfile     (after QUERY_ROBOT_CONFIG):
             2 → fwVersion    (app fw string, also aliased to "fwVersion")
             3 → mcuVersion   (MCU fw string, also aliased to "mcuVersion")
             4 → brand        ("Lymow")
             5 → ipAddress
             6 → macAddress
             7 → sn
             8 → rtkSn
             9 → simId
            10 → wheelVer
            11 → knifeVer
     12  PbCleanInfo:
             1 cleanTime       int32 (s)
             2 cleanArea       float (m²)
             3 areaInfo → cleanZoneIds
             4 remainCleanTime int32 (s)
             5 cleanPercent    float
             6 mapArea         float (m²)
     17  PbRobotConfig (after QUERY_ROBOT_CONFIG):
             1 cutHeight → state["cutHeight"]
             7 cleanMode → state["robotCleanMode"] + state["cleanMode"] (string)
             ... (full config in state["robotConfig"])
     18  outputCtrl        int32
     14  PbPose pose      → live local robot pose {x,y,theta,z}
     23  PbBtMap           → state["btMap"] = decode_btmap(...)
     24  PbPose chargingStationLoc → state["chargingStationLoc"]
     26  PbRobotLLACoords robotLlaCoords → schema-supported lat/lon/alt; often absent
     31  PbPoint robotPosePib → fallback local robot x/y on the mower map
     34  PbNetDetailInfo   → state["netDetailInfo"]
     35  PbRtkDiagnosticL1 → state["rtkDiagnosticL1"] + state["rtkStatus"]
     36  PbRtkDiagnosticL2 → state["rtkDiagnosticL2"]
    """
    state: dict[str, Any] = {}
    root = _wire_parse(raw)

    for fno, key in [(1, "msgId"), (2, "version")]:
        v = _gv(root, fno)
        if v is not None: state[key] = v

    err = _packed_ints(root, 3)
    if err: state["errorCodes"] = err; state["errorCode"] = err[0]
    warn = _packed_ints(root, 4)
    if warn: state["warningCodes"] = warn

    # PbRobotInfo (field 5) — flat
    ri = _sub(root, 5)
    if ri:
        for fno, key in [
            (1,"robotStatus"),(2,"battery"),(3,"wifiSignalQuality"),
            (4,"lteSignalQuality"),(5,"btSignalQuality"),(6,"workStatus"),
        ]:
            v = _gv(ri, fno)
            if v is not None: state[key] = _s32(v)
        for fno, key in [(7,"isRecharging"),(8,"isCharging"),(9,"wifiWorking"),(10,"lteWorking")]:
            v = _gv(ri, fno)
            if v is not None: state[key] = bool(v)
    if "workStatus" in state: state["isOnline"] = True

    # PbDeviceProfile (field 10)
    dp = _sub(root, 10)
    if dp:
        s = _gs(dp, 2)
        if s: state["appFwVersion"] = s; state["fwVersion"] = s
        s = _gs(dp, 3)
        if s: state["mcuFwVersion"] = s; state["mcuVersion"] = s
        s = _gs(dp, 4)
        if s: state["brand"] = s
        s = _gs(dp, 5)
        if s: state["ipAddress"] = s
        for fno, key in [(6,"macAddress"),(7,"sn"),(8,"rtkSn"),(9,"simId"),(10,"wheelVer"),(11,"knifeVer")]:
            s = _gs(dp, fno)
            if s: state[key] = s

    # PbMap (field 11) — direct full map branch
    direct_map = _sub(root, 11)
    if direct_map:
        mp = decode_map_fields(direct_map)
        if mp:
            state["btMap"] = {**state.get("btMap", {}), **mp}
            if mp.get("enuBasePoint"):
                state["enu_base_point"] = mp["enuBasePoint"]
            if mp.get("chargingStationLoc"):
                state["chargingStationLoc"] = mp["chargingStationLoc"]

    # PbCleanInfo (field 12)
    ci = _sub(root, 12)
    if ci:
        v = _gv(ci, 1)
        if v is not None: state["cleanTime"] = v
        f = _gf(ci, 2)
        if f is not None: state["cleanArea"] = f
        v = _gv(ci, 4)
        if v is not None: state["remainCleanTime"] = v
        f = _gf(ci, 5)
        if f is not None: state["cleanPercent"] = f
        f = _gf(ci, 6)
        if f is not None: state["mapArea"] = f
        ai = _sub(ci, 3)
        if ai:
            zone_ids: list[str] = []
            for kind, val in ai.get(2, []):
                if kind == "L":
                    try: zone_ids.append(val.decode("utf-8"))
                    except: pass
            if zone_ids: state["cleanZoneIds"] = zone_ids

    # PbRobotConfig (field 17) — remote/control-level config, not zone config
    rc = _sub(root, 17)
    if rc:
        cfg: dict[str, Any] = {}
        for fno, key in [
            (2,"rcCutSpeed"),(3,"rcCutHeight"),(6,"audioVolume"),(8,"signal"),
            (12,"camLedStatus"),(13,"vehLedStatus"),(16,"resumeBat"),
            (19,"scheduleId"),(20,"schedulePathOffset"),(21,"timezoneOffset"),
        ]:
            v = _gv(rc, fno)
            if v is not None: cfg[key] = _s32(v)
        for fno, key in [
            (4,"rcRaiseCutHeight"),(5,"rcLowerCutHeight"),(7,"isOpenLed"),
            (10,"cmdCellularSwitch"),(11,"metric_4g"),(22,"dockOnError"),
        ]:
            v = _gv(rc, fno)
            if v is not None: cfg[key] = bool(v)
        if cfg:
            state["robotConfig"] = cfg
            # Compatibility aliases used by existing number/sensor entities.
            if "rcCutHeight" in cfg:
                state["cutHeight"] = cfg["rcCutHeight"]
            if "rcCutSpeed" in cfg:
                state["cutSpeed"] = cfg["rcCutSpeed"]

    # PbPose / live robot pose in local ENU/map coordinates (field 14)
    # This is the most useful live position field. The official app and other
    # integrations derive GPS from this local pose + btMap.enuBasePoint.
    pose14 = _sub(root, 14)
    if pose14:
        robot_pose = _decode_pose(pose14)
        if robot_pose:
            state["pose"] = robot_pose
            state["robotLoc"] = robot_pose

    # outputCtrl (field 18)
    v = _gv(root, 18)
    if v is not None: state["outputCtrl"] = v

    # PbBtMap (field 23)
    for kind, btmap_val in root.get(23, []):
        if kind == "L":
            btmap = decode_btmap(btmap_val)
            if btmap.get("zones") or btmap.get("zone_count") or btmap.get("enuBasePoint"):
                state["btMap"] = btmap
                # Convenience alias used by device_tracker/state helpers.
                if btmap.get("enuBasePoint"):
                    state["enu_base_point"] = btmap["enuBasePoint"]
            break

    # chargingStationLoc / PbPose (field 24) — local map coordinates
    pose = _sub(root, 24)
    if pose:
        dock = _decode_pose(pose)
        if dock:
            state["chargingStationLoc"] = dock

    # PbRobotLLACoords / real GPS/RTK position (field 26)
    lla = _sub(root, 26)
    if lla:
        robot_lla = _decode_lla(lla)
        if robot_lla:
            state["robotLlaCoords"] = robot_lla
            # Home Assistant tracker-friendly aliases
            if "latitude" in robot_lla:
                state["latitude"] = robot_lla["latitude"]
            if "longitude" in robot_lla:
                state["longitude"] = robot_lla["longitude"]
            if "altitude" in robot_lla:
                state["altitude"] = robot_lla["altitude"]

    # PbPoint / fallback robot position in local map coordinates (field 31)
    rp = _sub(root, 31)
    if rp:
        robot_pose_pib = _decode_point(rp)
        if robot_pose_pib:
            state["robotPosePib"] = robot_pose_pib
            # Prefer field 14 pose when present because it also carries heading/theta.
            if "robotLoc" not in state:
                state["robotLoc"] = robot_pose_pib

    # PbNetDetailInfo (field 34)
    nd = _sub(root, 34)
    if nd:
        net: dict[str, Any] = {}
        for fno, key in [(1,"currentNet"),(4,"wifiSignal"),(5,"simCardStatus"),(7,"simSignal"),(8,"simRegistration")]:
            v = _gv(nd, fno)
            if v is not None: net[key] = v
        v = _gv(nd, 9)
        if v is not None: net["simConnection"] = bool(v)
        for fno, key in [(2,"wifiName"),(3,"wifiIp"),(6,"simIp"),(10,"simIccid")]:
            s = _gs(nd, fno)
            if s: net[key] = s
        if net:
            state["netDetailInfo"] = net
            if "wifiIp" in net and "ipAddress" not in state:
                state["ipAddress"] = net["wifiIp"]
            if "wifiName" in net and "wifiSsid" not in state:
                state["wifiSsid"] = net["wifiName"]

    # PbRtkDiagnosticL1 (field 35)
    rd = _sub(root, 35)
    if rd:
        rtk: dict[str, Any] = {}
        for fno, key in [(1,"rtkStatus"),(3,"satelliteCount"),(10,"baseStationStatus")]:
            v = _gv(rd, fno)
            if v is not None: rtk[key] = v
        for fno, key in [(2,"precision"),(11,"baseDataErrorRate")]:
            f = _gf(rd, fno)
            if f is not None: rtk[key] = f
        if rtk:
            state["rtkDiagnosticL1"] = rtk
            if "rtkStatus" in rtk: state["rtkStatus"] = rtk["rtkStatus"]

    # PbRtkDiagnosticL2 (field 36)
    rd2 = _sub(root, 36)
    if rd2:
        rtk2: dict[str, Any] = {}
        for fno, key in [
            (2, "loraBps0"), (3, "loraBps1"), (4, "loraBps2"),
            (8, "cwRatio0"), (9, "cwRatio1"), (10, "cwRatio2"),
            (11, "antValue0"), (12, "antValue1"), (13, "antValue2"),
        ]:
            v = _gv(rd2, fno)
            if v is not None:
                rtk2[key] = _s32(v)
        for fno, key in [
            (1, "diffAge"), (5, "hwDc0"), (6, "hwDc1"), (7, "hwDc2"),
        ]:
            f = _gf(rd2, fno)
            if f is not None:
                rtk2[key] = f
        if rtk2:
            state["rtkDiagnosticL2"] = rtk2

    # PbLocalizationInfo (field 6) — fallback RTK/location
    loc = _sub(root, 6)
    if loc and "rtkDiagnosticL1" not in state:
        loc_info: dict[str, Any] = {}
        v = _gv(loc, 1)
        if v is not None:
            loc_info["numSatellites"] = v
            loc_info["satelliteCount"] = v
        f = _gf(loc, 2)
        if f is not None:
            loc_info["horizontalAccuracy"] = f
            loc_info["precision"] = f
        f = _gf(loc, 3)
        if f is not None:
            loc_info["verticalAccuracy"] = f
        v = _gv(loc, 4)
        if v is not None:
            loc_info["positionQuality"] = v
            loc_info["rtkStatus"] = v
        v = _gv(loc, 5)
        if v is not None:
            loc_info["locNodeStatus"] = v
        if loc_info:
            state["localizationInfo"] = loc_info
            state["rtkDiagnosticL1"] = loc_info
            if "rtkStatus" in loc_info:
                state["rtkStatus"] = loc_info["rtkStatus"]

    known_root = {1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 14, 16, 17, 18, 22, 23, 24, 26, 31, 34, 35, 36}
    unknown = {k: v for k, v in root.items() if k not in known_root}
    if unknown:
        state["_unknown_root_fields"] = {
            k: [
                (kind, val.hex() if isinstance(val, (bytes, bytearray)) else val)
                for kind, val in entries
            ]
            for k, entries in unknown.items()
        }

    return state


def decode_pboutput_envelope(envelope_bytes: bytes) -> dict[str, Any]:
    """Decode a JSON-enveloped PbOutput message into a flat state dict."""
    raw = unwrap_envelope(envelope_bytes)
    if raw is None:
        return {}
    return decode_pboutput(raw)
