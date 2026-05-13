"""Lymow protocol layer — protobuf-first encode/decode + btMap wire parser.

This module uses the generated protobuf classes for normal PbInput/PbOutput
handling and keeps the low-level wire parser only for Lymow's nested btMap
queryAck blobs, where parts of the recovered .proto are incomplete/opaque.

Generated protobuf module location expected by this integration:
    custom_components/lymow/proto/lymow_pb2.py
"""
from __future__ import annotations

import base64
import json
import logging
import re
import struct
from dataclasses import dataclass, field
from typing import Any

from .proto import lymow_pb2 as pb

_LOGGER = logging.getLogger(__name__)

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

# cleanMode int -> string (PbZoneConfig.cleanMode values)
CLEAN_MODE_INT = {
    0: "NONE",
    1: "ZIGZAG_MODE",
    2: "CHESS_BOARD_MODE",
    3: "PERIMETER_LAPS_ONLY_MODE",
    4: "ADAPTIVE_ZIGZAG_MODE",
}
CLEAN_MODE_STR = {v: k for k, v in CLEAN_MODE_INT.items() if k != 0}


# ---------------------------------------------------------------------------
# Dataclasses used by HA entities/camera/selects
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ZoneInfo:
    hash_id: str
    name: str
    mow_order: int = 0
    is_enabled: bool = True
    polygon_points: list[tuple[float, float]] = field(default_factory=list)
    zone_config: dict[str, Any] = field(default_factory=dict)
    text_pos: tuple[float, float] | None = None
    zone_type: int | None = None
    area: float | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "hashId": self.hash_id,
            "name": self.name,
            "mowOrder": self.mow_order,
            "isEnabled": self.is_enabled,
            "points": self.polygon_points,
            "points_count": len(self.polygon_points),
        }
        if self.zone_type is not None:
            out["zoneType"] = self.zone_type
        if self.zone_config:
            out["zoneConfig"] = self.zone_config
        if self.text_pos is not None:
            out["textPos"] = {"x": self.text_pos[0], "y": self.text_pos[1]}
        if self.area is not None:
            out["area"] = self.area
        return out


@dataclass(slots=True)
class ChannelInfo:
    hash_id: str
    zone1: str = ""
    zone2: str = ""
    is_valid: bool | None = None
    is_docking_channel: bool = False
    polygon_points: list[tuple[float, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "hashId": self.hash_id,
            "zone1": self.zone1,
            "zone2": self.zone2,
            "isDockingChannel": self.is_docking_channel,
            "points": self.polygon_points,
            "points_count": len(self.polygon_points),
        }
        if self.is_valid is not None:
            out["isValid"] = self.is_valid
        return out


@dataclass(slots=True)
class ZoneCatalog:
    zones: list[ZoneInfo] = field(default_factory=list)
    channels: list[ChannelInfo] = field(default_factory=list)
    zones_by_hashid: dict[str, ZoneInfo] = field(default_factory=dict)
    runtime_config: dict[str, Any] | None = None
    enu_base_point: dict[str, Any] | None = None
    charging_station_loc: dict[str, Any] | None = None

    def to_btmap_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "zones": [z.to_dict() for z in self.zones],
            "zone_count": len(self.zones),
            "zones_with_points": sum(1 for z in self.zones if z.polygon_points),
            "channels": [c.to_dict() for c in self.channels],
            "channels_with_points": sum(1 for c in self.channels if c.polygon_points),
        }
        if self.runtime_config:
            out["runTimeConfig"] = self.runtime_config
            for k in ("cutHeight", "cutSpeed", "moveSpeed"):
                if k in self.runtime_config:
                    out[k] = self.runtime_config[k]
        if self.enu_base_point:
            out["enuBasePoint"] = self.enu_base_point
        if self.charging_station_loc:
            out["chargingStationLoc"] = self.charging_station_loc
        return out


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------

def wrap_envelope(raw: bytes) -> str:
    """Wrap raw protobuf bytes in Lymow/AWS IoT JSON envelope."""
    return json.dumps({"message": base64.b64encode(raw).decode("ascii")})


def unwrap_envelope(envelope_bytes: bytes) -> bytes | None:
    """Unwrap JSON {message:<base64>} or accept raw/base64 payloads."""
    if not envelope_bytes:
        return None
    stripped = envelope_bytes.lstrip()
    if stripped.startswith(b"{"):
        try:
            obj = json.loads(envelope_bytes.decode("utf-8"))
            for key in ("message", "value", "data", "payload"):
                v = obj.get(key)
                if isinstance(v, str):
                    return base64.b64decode(v)
        except Exception:
            _LOGGER.debug("Failed to unwrap JSON MQTT envelope", exc_info=True)
            return None
    try:
        return base64.b64decode(envelope_bytes, validate=True)
    except Exception:
        # Some tests/callers may already pass raw protobuf bytes.
        return envelope_bytes




# ---------------------------------------------------------------------------
# Minimal raw encoder fallback for fields that are not correctly represented
# by the recovered .proto. Keep this limited: normal commands use pb.PbInput.
# ---------------------------------------------------------------------------

def _raw_enc_varint(value: int) -> bytes:
    if value < 0:
        value &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        out.append(b | 0x80 if value else b)
        if not value:
            return bytes(out)

def _raw_enc_i32(field_no: int, value: int) -> bytes:
    return _raw_enc_varint((field_no << 3) | 0) + _raw_enc_varint(value)

def _raw_enc_len(field_no: int, data: bytes) -> bytes:
    return _raw_enc_varint((field_no << 3) | 2) + _raw_enc_varint(len(data)) + data


# ---------------------------------------------------------------------------
# PbInput encoders — protobuf first
# ---------------------------------------------------------------------------

def _new_input() -> pb.PbInput:
    msg = pb.PbInput()
    msg.version = PB_VERSION_4_9
    return msg


def encode_userctrl(user_ctrl: int) -> bytes:
    """Encode PbInput {version=40, userCtrl=N}."""
    msg = _new_input()
    msg.userCtrl = int(user_ctrl)
    return msg.SerializeToString()


def encode_query_map(query_index: int = 0) -> bytes:
    """Query full map via PbInput.btMap.queryMap."""
    msg = _new_input()
    msg.userCtrl = USER_CTRL_QUERY_MAP
    msg.btMap.queryIndex = int(query_index)
    msg.btMap.queryMap = True
    return msg.SerializeToString()


def encode_query_path(query_index: int = 0) -> bytes:
    """Query path data via PbInput.btMap.queryPath."""
    msg = _new_input()
    msg.userCtrl = USER_CTRL_QUERY_PATH
    msg.btMap.queryIndex = int(query_index)
    msg.btMap.queryPath = True
    return msg.SerializeToString()


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
    """Encode PbInput.debugSetting payload."""
    msg = _new_input()
    if upload_log:
        msg.debugSetting.uploadLog = True
    if upload_version:
        msg.debugSetting.uploadVersion = True
    if query_wifi_config:
        msg.debugSetting.queryWifiConfig = True
    if upload_robot_config:
        msg.debugSetting.uploadRobotConfig = True
    if upload_task_config:
        msg.debugSetting.uploadTaskConfig = True
    if exec_cmd:
        msg.debugSetting.execCmd = exec_cmd
    return msg.SerializeToString()


def encode_query_device_profile() -> bytes:
    return encode_debug_setting(upload_version=True, upload_robot_config=True)


def encode_query_wifi_config_debug() -> bytes:
    return encode_debug_setting(query_wifi_config=True)


def encode_upload_robot_config() -> bytes:
    """Trigger robotConfig broadcast without userCtrl."""
    return encode_debug_setting(upload_robot_config=True)


def encode_app_connect(client_uuid: str) -> bytes:
    msg = _new_input()
    msg.appConnect = 1
    msg.uuid = client_uuid
    return msg.SerializeToString()


def encode_start_zones(zone_hash_ids: list[str]) -> bytes:
    """Start mowing selected zones using PbInput.map.goZones."""
    msg = _new_input()
    msg.userCtrl = USER_CTRL_CLEAN
    for i, hash_id in enumerate(zone_hash_ids, start=1):
        if not hash_id:
            continue
        zone = msg.map.goZones.add()
        zone.basicInfo.hashId = hash_id
        zone.basicInfo.mowOrder = i
    return msg.SerializeToString()


def encode_set_cut_height(cut_height_mm: int) -> bytes:
    msg = _new_input()
    msg.map.runTimeConfig.cutHeight = int(cut_height_mm)
    return msg.SerializeToString()


def encode_set_clean_mode(mode_int: int) -> bytes:
    """Set global mowing mode.

    This is intentionally encoded with the tiny raw fallback instead of
    ``pb.PbInput().robotConfig``: the recovered Python schema maps
    PbRobotConfig field 7 as ``isOpenLed``, while live captures from the app
    showed the clean-mode command using PbInput.robotConfig field 7 as an int.
    Using pb2 here would turn the value into a boolean and could toggle LED
    state instead of setting the mowing mode.
    """
    robot_config = _raw_enc_i32(7, int(mode_int))
    return _raw_enc_i32(2, PB_VERSION_4_9) + _raw_enc_len(13, robot_config)


def encode_set_rr_config(
    *,
    enable_rr: bool,
    recharge_bat: int | None = None,
    resume_bat: int | None = None,
    period_start_hour: int | None = None,
    period_start_minute: int | None = None,
    period_end_hour: int | None = None,
    period_end_minute: int | None = None,
) -> bytes:
    """Encode no-userCtrl robotConfig.rrConfig update."""
    msg = _new_input()
    rr = msg.robotConfig.rrConfig
    rr.enableRr = bool(enable_rr)
    if recharge_bat is not None:
        rr.rechargeBat = int(recharge_bat)
    if resume_bat is not None:
        rr.resumeBat = int(resume_bat)
    if period_start_hour is not None:
        rr.resumePeriodStart.hour = int(period_start_hour)
    if period_start_minute is not None:
        rr.resumePeriodStart.minute = int(period_start_minute)
    if period_end_hour is not None:
        rr.resumePeriodEnd.hour = int(period_end_hour)
    if period_end_minute is not None:
        rr.resumePeriodEnd.minute = int(period_end_minute)
    msg.debugSetting.uploadRobotConfig = True
    return msg.SerializeToString()


def build_initial_query_packets(
    query_index: int = 0,
    client_uuid: str | None = None,
) -> list[bytes]:
    """Startup packet set. Kept compatible with old coordinator imports."""
    packets: list[bytes] = []
    if client_uuid:
        packets.append(encode_app_connect(client_uuid))
    packets.extend([
        encode_query_map(query_index),
        encode_query_schedules(),
        encode_upload_robot_config(),
    ])
    return packets


def build_refresh_query_packets(client_uuid: str | None = None) -> list[bytes]:
    """Light periodic refresh packet set."""
    packets: list[bytes] = []
    if client_uuid:
        packets.append(encode_app_connect(client_uuid))
    packets.extend([
        encode_query_cleaning_info(),
        encode_query_net_detail(),
        encode_query_robot_config(),
        encode_query_wifi_4g(),
        encode_query_rtk_l1(),
        encode_query_rtk_l2(),
    ])
    return packets


# ---------------------------------------------------------------------------
# PbOutput decode — protobuf first
# ---------------------------------------------------------------------------

def decode_pboutput(raw: bytes) -> pb.PbOutput:
    """Parse raw protobuf bytes as PbOutput."""
    msg = pb.PbOutput()
    msg.ParseFromString(raw)
    return msg


def decode_pboutput_envelope(envelope_bytes: bytes) -> pb.PbOutput | None:
    """Decode JSON-enveloped/raw payload into PbOutput."""
    raw = unwrap_envelope(envelope_bytes)
    if not raw:
        return None
    return decode_pboutput(raw)


def populated_fields(msg: pb.PbOutput) -> list[str]:
    return [field.name for field, _ in msg.ListFields()]


# ---------------------------------------------------------------------------
# Low-level wire parser for opaque btMap/queryAck blobs
# ---------------------------------------------------------------------------

def _dec_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    for _ in range(10):
        if pos >= len(buf):
            raise ValueError("truncated varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
    raise ValueError("varint overflow")


def _wire_parse(buf: bytes) -> dict[int, list[tuple[str, Any]]]:
    if not isinstance(buf, (bytes, bytearray)) or not buf:
        return {}
    out: dict[int, list[tuple[str, Any]]] = {}
    pos = 0
    while pos < len(buf):
        try:
            tag, pos = _dec_varint(buf, pos)
            fno, wt = tag >> 3, tag & 7
            if wt == 0:
                v, pos = _dec_varint(buf, pos)
                out.setdefault(fno, []).append(("v", v))
            elif wt == 1:
                out.setdefault(fno, []).append(("f64", buf[pos:pos + 8]))
                pos += 8
            elif wt == 2:
                ln, pos = _dec_varint(buf, pos)
                out.setdefault(fno, []).append(("L", buf[pos:pos + ln]))
                pos += ln
            elif wt == 5:
                out.setdefault(fno, []).append(("f32", buf[pos:pos + 4]))
                pos += 4
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
        try:
            return e[0][1].decode("utf-8")
        except Exception:
            return None
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
    return v - (1 << 64) if v >= (1 << 63) else v


def _wire_str(blob: bytes) -> str | None:
    try:
        s = blob.decode("utf-8")
        if s.isprintable():
            return s
    except Exception:
        pass
    return None


def _decode_point_dict(fields: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    x = _gf(fields, 1)
    y = _gf(fields, 2)
    if x is not None:
        out["x"] = x
    if y is not None:
        out["y"] = y
    return out


def _decode_pose_dict(fields: dict) -> dict[str, Any]:
    out = _decode_point_dict(fields)
    theta = _gf(fields, 3)
    z = _gf(fields, 4)
    if theta is not None:
        out["theta"] = theta
        out["heading"] = theta
    if z is not None:
        out["z"] = z
    return out


def _decode_lla_dict(fields: dict) -> dict[str, Any]:
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


def _decode_polygon_points(fields: dict) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for kind, val in fields.get(1, []):
        if kind != "L":
            continue
        pf = _wire_parse(val)
        x = _gf(pf, 1)
        y = _gf(pf, 2)
        if x is not None and y is not None:
            pts.append((round(x, 4), round(y, 4)))
    return pts


def _polygon_area(pts: list[tuple[float, float]]) -> float:
    if len(pts) < 3:
        return 0.0
    total = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        total += x1 * y2 - x2 * y1
    return abs(total) * 0.5


def _decode_zone_config_fields(fields: dict) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    for fno, key in [
        (1, "cutHeight"), (5, "brushSpeed"), (6, "cutSpeed"), (7, "cleanMode"),
        (8, "cleanDir"), (9, "pathSpacing"), (10, "perimeterMowLaps"),
        (11, "perimeterMowDir"), (12, "noGoMowLaps"), (13, "obsDecMode"),
        (15, "startProgress"), (16, "relativeCleanDir"), (19, "followDetectMode"),
    ]:
        v = _gv(fields, fno)
        if v is not None:
            cfg[key] = _s32(v) if key in {"cleanDir"} else v
    for fno, key in [
        (2, "raiseCutHeight"), (3, "lowerCutHeight"), (14, "pathOrder"),
        (17, "lineFollowMode"), (18, "disableOuterDischarge"),
    ]:
        v = _gv(fields, fno)
        if v is not None:
            cfg[key] = bool(v)
    f = _gf(fields, 4)
    if f is not None:
        cfg["moveSpeed"] = f
    return cfg


def _parse_pbzone_basicinfo(buf: bytes) -> dict[str, Any]:
    f = _wire_parse(buf)
    out: dict[str, Any] = {
        "type": _gv(f, 1),
        "name": _gs(f, 2) or "",
        "hashId": _gs(f, 3) or "",
        "isEnabled": bool(_gv(f, 4)) if _gv(f, 4) is not None else True,
        "zoneRename": _gs(f, 6) or "",
        "updateTime": _gv(f, 7),
        "mowOrder": _gv(f, 8) or 0,
        "polygon": [],
        "textPos": None,
    }
    poly = _sub(f, 5)
    if poly:
        out["polygon"] = _decode_polygon_points(poly)
    text_pos = _sub(f, 9)
    if text_pos:
        p = _decode_point_dict(text_pos)
        if "x" in p and "y" in p:
            out["textPos"] = (p["x"], p["y"])
    return out


def _rectangle_from_bounds(b00: Any, b11: Any) -> list[tuple[float, float]]:
    try:
        x1, y1 = float(b00[0]), float(b00[1])
        x2, y2 = float(b11[0]), float(b11[1])
    except Exception:
        return []
    if x1 == x2 or y1 == y2:
        return []
    return [
        (round(x1, 4), round(y1, 4)),
        (round(x2, 4), round(y1, 4)),
        (round(x2, 4), round(y2, 4)),
        (round(x1, 4), round(y2, 4)),
    ]


def _decode_pp_basic_info(fields: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    b00 = _sub(fields, 1)
    if b00:
        p = _decode_point_dict(b00)
        if "x" in p and "y" in p:
            out["bound_00"] = (p["x"], p["y"])
    b11 = _sub(fields, 2)
    if b11:
        p = _decode_point_dict(b11)
        if "x" in p and "y" in p:
            out["bound_11"] = (p["x"], p["y"])
    area = _gv(fields, 3)
    if area is not None:
        out["ppArea"] = area
    cw = _gv(fields, 4)
    if cw is not None:
        out["isClockwise"] = bool(cw)
    inner = _sub(fields, 5)
    if inner:
        p = _decode_point_dict(inner)
        if "x" in p and "y" in p:
            out["innerPoint"] = (p["x"], p["y"])
    return out


# ---------------------------------------------------------------------------
# PbMap/PbBtMap catalog parsers
# ---------------------------------------------------------------------------

def parse_map_fields(map_data: dict[int, list[tuple[str, Any]]]) -> ZoneCatalog:
    """Parse a PbMap wire dict into ZoneCatalog."""
    catalog = ZoneCatalog()

    enu = _sub(map_data, 7)
    if enu:
        catalog.enu_base_point = _decode_lla_dict(enu) or None

    dock = _sub(map_data, 4)
    if dock:
        catalog.charging_station_loc = _decode_pose_dict(dock) or None

    rtc = _sub(map_data, 13)
    if rtc:
        runtime: dict[str, Any] = {}
        v = _gv(rtc, 1)
        if v is not None:
            runtime["cutHeight"] = v
        f = _gf(rtc, 4)
        if f is not None:
            runtime["moveSpeed"] = f
        v = _gv(rtc, 6)
        if v is not None:
            runtime["cutSpeed"] = v
        if runtime:
            catalog.runtime_config = runtime

    # PbMap.goZones (field 1)
    hash_re = re.compile(r"^[A-Za-z0-9_]{4,32}$")
    for kind, zval in map_data.get(1, []):
        if kind != "L":
            continue
        z = _wire_parse(zval)
        basic = _sub(z, 1)
        if not basic:
            continue
        bi = _parse_pbzone_basicinfo(z[1][0][1])
        hash_id = bi.get("hashId") or ""
        if not hash_id or not hash_re.match(hash_id):
            continue
        points = list(bi.get("polygon") or [])

        # Fallback from ppBasicInfo bounds if no polygon points exist.
        pp = _sub(z, 3)
        if not points and pp:
            pp_info = _decode_pp_basic_info(pp)
            if pp_info.get("bound_00") and pp_info.get("bound_11"):
                points = _rectangle_from_bounds(pp_info["bound_00"], pp_info["bound_11"])

        zone_cfg: dict[str, Any] = {}
        zcfg = _sub(z, 2)
        if zcfg:
            zone_cfg = _decode_zone_config_fields(zcfg)

        name = bi.get("name") or bi.get("zoneRename") or hash_id
        text_pos = bi.get("textPos")
        zi = ZoneInfo(
            hash_id=hash_id,
            name=name,
            mow_order=int(bi.get("mowOrder") or 0),
            is_enabled=bool(bi.get("isEnabled")),
            polygon_points=points,
            zone_config=zone_cfg,
            text_pos=text_pos if isinstance(text_pos, tuple) else None,
            zone_type=bi.get("type"),
            area=round(_polygon_area(points), 3) if points else None,
        )
        catalog.zones.append(zi)
        catalog.zones_by_hashid[zi.hash_id] = zi

    # PbMap.channels (field 3)
    for kind, cval in map_data.get(3, []):
        if kind != "L":
            continue
        chf = _wire_parse(cval)
        hash_id = _gs(chf, 1) or ""
        if not hash_id:
            continue
        poly = _sub(chf, 5)
        pts = _decode_polygon_points(poly) if poly else []
        is_valid_raw = _gv(chf, 4)
        catalog.channels.append(ChannelInfo(
            hash_id=hash_id,
            zone1=_gs(chf, 2) or "",
            zone2=_gs(chf, 3) or "",
            is_valid=bool(is_valid_raw) if is_valid_raw is not None else None,
            is_docking_channel=bool(_gv(chf, 6)) if _gv(chf, 6) is not None else False,
            polygon_points=pts,
        ))

    return catalog


def parse_zone_catalog(bt_map: pb.PbBtMap) -> ZoneCatalog:
    """Parse PbBtMap QUERY_MAP response into ZoneCatalog.

    The rich map is usually hidden inside:
      PbBtMap.queryAck -> queryAck field 3 -> PbMap blob
    """
    if bt_map is None or bt_map.ByteSize() == 0:
        return ZoneCatalog()

    root = _wire_parse(bt_map.SerializeToString())

    # Path used by real QUERY_MAP response: btMap field 2 = queryAck.
    try:
        if 2 in root and root[2][0][0] == "L":
            qa = _wire_parse(root[2][0][1])
            if 3 in qa and qa[3][0][0] == "L":
                inner = _wire_parse(qa[3][0][1])
                return parse_map_fields(inner)
    except Exception:
        _LOGGER.debug("Failed parsing btMap.queryAck map blob", exc_info=True)

    # Fallback: sometimes the bytes may already look like PbMap-ish fields.
    return parse_map_fields(root)


def decode_btmap(raw: bytes) -> dict[str, Any]:
    """Backward-compatible function returning btMap as dict."""
    if not raw:
        return {}
    # raw may be PbBtMap bytes, not PbMap bytes.
    msg = pb.PbBtMap()
    try:
        msg.ParseFromString(raw)
        return parse_zone_catalog(msg).to_btmap_dict()
    except Exception:
        return parse_map_fields(_wire_parse(raw)).to_btmap_dict()


def decode_pbmap(raw: bytes) -> dict[str, Any]:
    """Decode standalone PbMap file downloaded from S3 backup maps."""
    if not raw:
        return {}
    return parse_map_fields(_wire_parse(raw)).to_btmap_dict()


# ---------------------------------------------------------------------------
# Schedule decoder placeholder-compatible functions
# ---------------------------------------------------------------------------

def decode_schedules(schedule_msg: Any) -> list[dict[str, Any]]:
    """Best-effort schedule decoder placeholder.

    PbSchedule appears as an empty placeholder in the recovered schema, so this
    keeps a safe return type for entities. We can expand this once schedules are
    needed with full wire parsing.
    """
    if schedule_msg is None or getattr(schedule_msg, "ByteSize", lambda: 0)() == 0:
        return []
    return [{"rawByteSize": schedule_msg.ByteSize()}]
