"""Lymow protobuf encode/decode — raw bytes, no compiled pb2 required.

Wire format on MQTT topics:
    publish  /device/{thing}/pbinput   → JSON {"message": "<base64 PbInput>"}
    receive  /device/{thing}/pboutput  → JSON {"message": "<base64 PbOutput>"}
    receive  /device/{thing}/notify-app → JSON {"robotState": "online"|"offline", ...}

PbInput field map (confirmed from decompiled.js):
    field 2  version    int32  (always 40 = PB_VERSION_4_9)
    field 5  userCtrl   int32
    field 6  btMap      message  { field 1: queryMap bool }

PbOutput field map (confirmed from decode_pboutput + decompiled.js):
    field 3  errorCodes     repeated int32 (packed)
    field 4  warningCodes   repeated int32 (packed)
    field 5  robotInfo      message
        field 1  robotStatus  message
            field 1   robotStatus        int32
            field 2   battery            int32   (0-100 %)
            field 3   wifiSignalQuality  int32
            field 4   lteSignalQuality   int32
            field 5   btSignalQuality    int32
            field 6   workStatus         int32
            field 7   isRecharging       bool
            field 8   isCharging         bool
            field 9   wifiWorking        bool
            field 10  lteWorking         bool
    field 34 netDetailInfo  message
        field 1  currentNet      int32
        field 2  wifiName        string
        field 3  wifiIp          string
        field 4  wifiSignal      int32
        field 5  simCardStatus   int32
        field 6  simIp           string
        field 7  simSignal       int32
        field 8  simRegistration int32
        field 9  simConnection   bool
        field 10 simIccid        string
    field 35 rtkDiagnosticL1  message
        field 1  rtkStatus          int32
        field 2  precision          float (wire type 5)
        field 3  satelliteCount     int32
        field 10 baseStationStatus  int32
        field 11 baseDataErrorRate  float (wire type 5)
"""
from __future__ import annotations

import base64
import json
import struct
from typing import Any

# ── PB version ────────────────────────────────────────────────

PB_VERSION_4_9 = 40  # PbVersion.PB_VERSION_4_9

# ── USER_CTRL command codes ────────────────────────────────────

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


# ── Low-level wire encoder ─────────────────────────────────────

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


def _enc_field(field_no: int, wire_type: int) -> bytes:
    return _enc_varint((field_no << 3) | wire_type)


def _enc_int32(field_no: int, value: int) -> bytes:
    """Encode a varint field."""
    return _enc_field(field_no, 0) + _enc_varint(value)


def _enc_len(field_no: int, data: bytes) -> bytes:
    """Encode a length-delimited field."""
    return _enc_field(field_no, 2) + _enc_varint(len(data)) + data


# ── PbInput encoders ───────────────────────────────────────────

def encode_userctrl(user_ctrl: int) -> bytes:
    """Minimal PbInput {version=40, userCtrl=N}."""
    return _enc_int32(2, PB_VERSION_4_9) + _enc_int32(5, user_ctrl)


def encode_query_map() -> bytes:
    """PbInput for QUERY_MAP with btMap.queryMap=True.

    Without the queryMap flag the robot returns only a small state echo
    with no zone catalog. With it, we get the full PbMap + PbRunTimeConfig.
    btMap is field 6 (message); queryMap is its field 1 (bool/varint).
    """
    bt_map_inner = _enc_int32(1, 1)         # queryMap = true
    return (
        _enc_int32(2, PB_VERSION_4_9)        # version
        + _enc_int32(5, USER_CTRL_QUERY_MAP) # userCtrl = 19
        + _enc_len(6, bt_map_inner)          # btMap { queryMap: true }
    )


def encode_start_zones(zone_hash_ids: list[str]) -> bytes:
    """PbInput for CLEAN with optional zone list (field 7 = map.goZones)."""
    pb = _enc_int32(2, PB_VERSION_4_9) + _enc_int32(5, USER_CTRL_CLEAN)
    for i, hash_id in enumerate(zone_hash_ids, start=1):
        # map = field 7 > goZones repeated = field 2 > basicInfo = field 1
        # basicInfo: hashId = field 3 (string), mowOrder = field 8 (int)
        basic_info = (
            _enc_len(3, hash_id.encode())
            + _enc_int32(8, i)
        )
        go_zone = _enc_len(1, basic_info)
        map_msg = _enc_len(2, go_zone)
        pb += _enc_len(7, map_msg)
    return pb


# ── Envelope ───────────────────────────────────────────────────

def wrap_envelope(raw: bytes) -> str:
    """Wrap raw protobuf bytes in the JSON envelope used on MQTT topics."""
    return json.dumps({"message": base64.b64encode(raw).decode("ascii")})


def unwrap_envelope(envelope_bytes: bytes) -> bytes | None:
    """Strip JSON envelope, return raw protobuf bytes. Returns None on error."""
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


# ── Low-level wire decoder ─────────────────────────────────────

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


def _wire_parse(buf: bytes) -> dict[int, list[tuple[str, Any]]]:
    """Parse raw protobuf bytes into {field_no: [(kind, value), ...]}."""
    out: dict[int, list] = {}
    pos = 0
    while pos < len(buf):
        try:
            tag, pos = _dec_varint(buf, pos)
        except (ValueError, IndexError):
            break
        fno, wt = tag >> 3, tag & 7
        if wt == 0:
            v, pos = _dec_varint(buf, pos)
            out.setdefault(fno, []).append(("v", v))
        elif wt == 1:
            out.setdefault(fno, []).append(("f64", buf[pos:pos + 8]))
            pos += 8
        elif wt == 2:
            length, pos = _dec_varint(buf, pos)
            out.setdefault(fno, []).append(("L", buf[pos:pos + length]))
            pos += length
        elif wt == 5:
            out.setdefault(fno, []).append(("f32", buf[pos:pos + 4]))
            pos += 4
        else:
            break
    return out


def _get_varint(fields: dict, fno: int, default=None):
    entries = fields.get(fno)
    if entries:
        kind, val = entries[0]
        if kind == "v":
            return val
    return default


def _get_str(fields: dict, fno: int, default=None):
    entries = fields.get(fno)
    if entries:
        kind, val = entries[0]
        if kind == "L":
            try:
                return val.decode("utf-8")
            except Exception:
                pass
    return default


def _get_float32(fields: dict, fno: int, default=None):
    entries = fields.get(fno)
    if entries:
        kind, val = entries[0]
        if kind == "f32" and len(val) == 4:
            return round(struct.unpack("<f", val)[0], 4)
    return default


def _get_packed_varints(fields: dict, fno: int) -> list[int]:
    """Decode a packed repeated varint field."""
    result: list[int] = []
    for kind, val in fields.get(fno, []):
        if kind == "v":
            result.append(val)
        elif kind == "L" and isinstance(val, (bytes, bytearray)):
            pos = 0
            while pos < len(val):
                try:
                    v, pos = _dec_varint(val, pos)
                    result.append(v)
                except Exception:
                    break
    return result


# ── PbOutput → flat state dict ────────────────────────────────

def decode_pboutput(raw: bytes) -> dict[str, Any]:
    """Parse raw PbOutput bytes into a flat state dict matching existing entity keys.

    Returns a dict with the same keys as the previous shadow-based state so
    existing sensor/entity code works unchanged.
    """
    state: dict[str, Any] = {}
    root = _wire_parse(raw)

    # Error / warning codes (packed repeated int32)
    err = _get_packed_varints(root, 3)
    if err:
        state["errorCodes"] = err
        state["errorCode"]  = err[0]

    warn = _get_packed_varints(root, 4)
    if warn:
        state["warningCodes"] = warn

    # robotInfo (field 5) — fields directly in message, no sub-message nesting
    ri_entries = root.get(5)
    if ri_entries:
        ri_val = ri_entries[0][1]
        ri = _wire_parse(ri_val) if isinstance(ri_val, (bytes, bytearray)) else {}
        for fno, key in [
            (1, "robotStatus"),
            (2, "battery"),
            (3, "wifiSignalQuality"),
            (4, "lteSignalQuality"),
            (5, "btSignalQuality"),
            (6, "workStatus"),
        ]:
            v = _get_varint(ri, fno)
            if v is not None:
                # Signed int32: negative values are sign-extended to 64-bit
                if v >= (1 << 31):
                    v = v - (1 << 64)
                state[key] = v

        for fno, key in [
            (7, "isRecharging"),
            (8, "isCharging"),
            (9, "wifiWorking"),
            (10, "lteWorking"),
        ]:
            v = _get_varint(ri, fno)
            if v is not None:
                state[key] = bool(v)

    # rtkInfo (field 6 of root — NOT field 35 as originally assumed)
    rtk6_entries = root.get(6)
    if rtk6_entries:
        rtk6_val = rtk6_entries[0][1]
        rtk6 = _wire_parse(rtk6_val) if isinstance(rtk6_val, (bytes, bytearray)) else {}
        rtk: dict[str, Any] = {}
        for fno, key in [(1, "satelliteCount"), (4, "rtkStatus"), (5, "baseStationStatus")]:
            v = _get_varint(rtk6, fno)
            if v is not None:
                rtk[key] = v
        for fno, key in [(2, "precision"), (3, "baseDataErrorRate")]:
            f = _get_float32(rtk6, fno)
            if f is not None:
                rtk[key] = f
        if rtk:
            state["rtkDiagnosticL1"] = rtk
            if "rtkStatus" in rtk:
                state["rtkStatus"] = rtk["rtkStatus"]

    # Derive isOnline from workStatus presence
    if "workStatus" in state:
        state["isOnline"] = state["workStatus"] >= 0

    # netDetailInfo (field 34)
    nd_entries = root.get(34)
    if nd_entries:
        nd_val = nd_entries[0][1]
        nd = _wire_parse(nd_val) if isinstance(nd_val, (bytes, bytearray)) else {}
        net: dict[str, Any] = {}
        for fno, key in [(1, "currentNet"), (4, "wifiSignal"), (5, "simCardStatus"),
                          (7, "simSignal"), (8, "simRegistration")]:
            v = _get_varint(nd, fno)
            if v is not None:
                net[key] = v
        v = _get_varint(nd, 9)
        if v is not None:
            net["simConnection"] = bool(v)
        for fno, key in [(2, "wifiName"), (3, "wifiIp"), (6, "simIp"), (10, "simIccid")]:
            s = _get_str(nd, fno)
            if s:
                net[key] = s
        if net:
            state["netDetailInfo"] = net

    # field 35 kept for backward compat (may appear in some firmware versions)
    rtk35_entries = root.get(35)
    if rtk35_entries and "rtkDiagnosticL1" not in state:
        rtk35_val = rtk35_entries[0][1]
        rd = _wire_parse(rtk35_val) if isinstance(rtk35_val, (bytes, bytearray)) else {}
        rtk35: dict[str, Any] = {}
        for fno, key in [(1, "rtkStatus"), (3, "satelliteCount"), (10, "baseStationStatus")]:
            v = _get_varint(rd, fno)
            if v is not None:
                rtk35[key] = v
        for fno, key in [(2, "precision"), (11, "baseDataErrorRate")]:
            f = _get_float32(rd, fno)
            if f is not None:
                rtk35[key] = f
        if rtk35:
            state["rtkDiagnosticL1"] = rtk35
            if "rtkStatus" in rtk35:
                state["rtkStatus"] = rtk35["rtkStatus"]

    return state


def decode_pboutput_envelope(envelope_bytes: bytes) -> dict[str, Any]:
    """Decode a JSON-enveloped PbOutput message into a flat state dict."""
    raw = unwrap_envelope(envelope_bytes)
    if raw is None:
        return {}
    return decode_pboutput(raw)
