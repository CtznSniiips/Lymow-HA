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

USER_CTRL_CLEAN            = 1
USER_CTRL_DOCK             = 2
USER_CTRL_PAUSE            = 3
USER_CTRL_RESUME           = 4
USER_CTRL_QUERY_MAP        = 19
USER_CTRL_QUERY_SCHEDULES  = 20
USER_CTRL_PAUSE_DOCK       = 21
USER_CTRL_RESUME_DOCK      = 22
USER_CTRL_FORCE_REINIT     = 28
USER_CTRL_RECHARGE_DOCK    = 33
USER_CTRL_QUERY_CLEANING   = 24
USER_CTRL_QUERY_ROBOT_CFG  = 35
USER_CTRL_QUERY_NET_DETAIL = 53
USER_CTRL_QUERY_RTK_L1     = 57
USER_CTRL_QUERY_RTK_L2     = 58

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

def _enc_len(field_no: int, data: bytes) -> bytes:
    return _enc_varint((field_no << 3) | 2) + _enc_varint(len(data)) + data


# ── PbInput encoders ───────────────────────────────────────────

def encode_userctrl(user_ctrl: int) -> bytes:
    return _enc_i32(2, PB_VERSION_4_9) + _enc_i32(5, user_ctrl)

def encode_query_map() -> bytes:
    return (
        _enc_i32(2, PB_VERSION_4_9)
        + _enc_i32(5, USER_CTRL_QUERY_MAP)
        + _enc_len(6, _enc_i32(1, 1))
    )

def encode_start_zones(zone_hash_ids: list[str]) -> bytes:
    pb = _enc_i32(2, PB_VERSION_4_9) + _enc_i32(5, USER_CTRL_CLEAN)
    for i, hash_id in enumerate(zone_hash_ids, start=1):
        basic_info = _enc_len(3, hash_id.encode()) + _enc_i32(8, i)
        pb += _enc_len(7, _enc_len(2, _enc_len(1, basic_info)))
    return pb


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
    root = _wire_parse(raw)

    for kind, map_val in root.get(2, []):
        if kind != "L":
            continue
        map_data = _wire_parse(map_val)
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

    return {"zones": zones, "zone_count": zone_count or len(zones)}


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
     23  PbBtMap           → state["btMap"] = decode_btmap(...)
     24  PbPose chargingStationLoc → state["chargingStationLoc"]
     34  PbNetDetailInfo   → state["netDetailInfo"]
     35  PbRtkDiagnosticL1 → state["rtkDiagnosticL1"] + state["rtkStatus"]
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

    # PbRobotConfig (field 17)
    rc = _sub(root, 17)
    if rc:
        cfg: dict[str, Any] = {}
        for fno, key in [
            (1,"cutHeight"),(5,"brushSpeed"),(6,"cutSpeed"),(7,"cleanMode"),
            (8,"cleanDir"),(9,"pathSpacing"),(10,"perimeterMowLaps"),
            (11,"perimeterMowDir"),(12,"noGoMowLaps"),(13,"obsDecMode"),
            (15,"startProgress"),(16,"relativeCleanDir"),(19,"followDetectMode"),
        ]:
            v = _gv(rc, fno)
            if v is not None: cfg[key] = v
        for fno, key in [
            (2,"raiseCutHeight"),(3,"lowerCutHeight"),(14,"pathOrder"),
            (17,"lineFollowMode"),(18,"disableOuterDischarge"),
        ]:
            v = _gv(rc, fno)
            if v is not None: cfg[key] = bool(v)
        f = _gf(rc, 4)
        if f is not None: cfg["moveSpeed"] = f
        if cfg:
            state["robotConfig"] = cfg
            if "cutHeight" in cfg: state["cutHeight"] = cfg["cutHeight"]
            if "cleanMode" in cfg:
                state["robotCleanMode"] = cfg["cleanMode"]
                state["cleanMode"]      = CLEAN_MODE_INT.get(cfg["cleanMode"], "NONE")

    # outputCtrl (field 18)
    v = _gv(root, 18)
    if v is not None: state["outputCtrl"] = v

    # PbBtMap (field 23)
    for kind, btmap_val in root.get(23, []):
        if kind == "L":
            btmap = decode_btmap(btmap_val)
            if btmap.get("zones") or btmap.get("zone_count"):
                state["btMap"] = btmap
            break

    # chargingStationLoc / PbPose (field 24)
    pose = _sub(root, 24)
    if pose:
        dock: dict[str, Any] = {}
        for fno, key in [(1,"x"),(2,"y"),(3,"heading")]:
            f = _gf(pose, fno)
            if f is not None: dock[key] = f
        if dock: state["chargingStationLoc"] = dock

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
        if net: state["netDetailInfo"] = net

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

    # PbLocalizationInfo (field 6) — fallback RTK
    loc = _sub(root, 6)
    if loc and "rtkDiagnosticL1" not in state:
        rtk_loc: dict[str, Any] = {}
        for fno, key in [(1,"satelliteCount"),(4,"rtkStatus"),(5,"baseStationStatus")]:
            v = _gv(loc, fno)
            if v is not None: rtk_loc[key] = v
        for fno, key in [(2,"precision"),(3,"baseDataErrorRate")]:
            f = _gf(loc, fno)
            if f is not None: rtk_loc[key] = f
        if rtk_loc:
            state["rtkDiagnosticL1"] = rtk_loc
            if "rtkStatus" in rtk_loc: state["rtkStatus"] = rtk_loc["rtkStatus"]

    return state


def decode_pboutput_envelope(envelope_bytes: bytes) -> dict[str, Any]:
    """Decode a JSON-enveloped PbOutput message into a flat state dict."""
    raw = unwrap_envelope(envelope_bytes)
    if raw is None:
        return {}
    return decode_pboutput(raw)
