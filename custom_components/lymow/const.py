"""Constants for the Lymow integration"""

DOMAIN = "lymow"
MANUFACTURER = "Lymow"

CONF_EMAIL    = "email"
CONF_PASSWORD = "password"
CONF_REGION   = "region"
CONF_AUTH_METHOD = "auth_method"

AUTH_METHOD_PASSWORD = "password"
AUTH_METHOD_GOOGLE   = "google"

# Cognito Hosted UI domains (discovered via OpenID configuration endpoint)
COGNITO_DOMAINS: dict[str, str] = {
    "eu-west-1":      "eu-auth.lymow.com",
    "ap-southeast-2": "ap-auth.lymow.com",
    "us-east-2":      "us-auth.lymow.com",
    "ap-east-1":      "lymow.auth.ap-east-1.amazoncognito.com",
}

DEFAULT_SCAN_INTERVAL = 30  # seconds

# ─────────────────────────────────────────────────────────────
# AWS regions
# ─────────────────────────────────────────────────────────────
REGIONS = {
    "eu-west-1":      "Europe (Ireland)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "us-east-2":      "US East (Ohio)",
    "ap-east-1":      "Asia Pacific (Hong Kong)",
}

COGNITO_CONFIG: dict[str, dict] = {
    "eu-west-1": {
        "user_pool_id":     "eu-west-1_6qNPbnrrd",
        "client_id":        "3h1sqv3hishjiofbv8giskjgb0",
        "identity_pool_id": "eu-west-1:c905a69c-0153-401a-a879-0c50b892015b",
    },
    "ap-southeast-2": {
        "user_pool_id":     "ap-southeast-2_vNriuUNeQ",
        "client_id":        "2ch3nqqr0usf5sadvcrj2hp6ll",
        "identity_pool_id": "ap-southeast-2:87d0fe24-16af-4189-b02f-984a7ed14ee0",
    },
    "us-east-2": {
        "user_pool_id":     "us-east-2_GAyiLkZQf",
        "client_id":        "3ftv5jumkv375hic8dpdqodj8n",
        "identity_pool_id": "us-east-2:037db699-5df0-4ed2-92b8-0dd0f1843918",
    },
    "ap-east-1": {
        "user_pool_id":     "ap-east-1_23Lf1WZer",
        "client_id":        "46mirppdlu6mrbjd5bkiil0n20",
        "identity_pool_id": "ap-east-1:3e9265aa-f564-4083-8e1e-988e6cfdc446",
    },
}

API_ENDPOINTS: dict[str, dict] = {
    "eu-west-1": {
        "deviceBindingApi": "https://asjqh5wbtj.execute-api.eu-west-1.amazonaws.com/prod",
        "deviceProfileApi": "https://6ghz1zkccg.execute-api.eu-west-1.amazonaws.com/prod",
        "checkUpdateApi":   "https://eigc6a2ds9.execute-api.eu-west-1.amazonaws.com/prod",
        "userAccountApi":   "https://l3hazobjk0.execute-api.eu-west-1.amazonaws.com/prod",
        "s3Api":            "https://3q1zxz98l2.execute-api.eu-west-1.amazonaws.com/prod",
        "iotDomain":        "a3j5zqqo5iuph9-ats.iot.eu-west-1.amazonaws.com",
    },
    "ap-southeast-2": {
        "deviceBindingApi": "https://1sfa49lnl8.execute-api.ap-southeast-2.amazonaws.com/prod",
        "deviceProfileApi": "https://7k2iuc99h7.execute-api.ap-southeast-2.amazonaws.com/prod",
        "checkUpdateApi":   "https://v7tlj1gnw7.execute-api.ap-southeast-2.amazonaws.com/prod",
        "userAccountApi":   "https://l2gobpcoqc.execute-api.ap-southeast-2.amazonaws.com/prod",
        "s3Api":            "https://2xipi98nw3.execute-api.ap-southeast-2.amazonaws.com/prod",
        "iotDomain":        "a3j5zqqo5iuph9-ats.iot.ap-southeast-2.amazonaws.com",
    },
    "us-east-2": {
        "deviceBindingApi": "https://453ahng0z4.execute-api.us-east-2.amazonaws.com/prod",
        "deviceProfileApi": "https://xuw7gtx113.execute-api.us-east-2.amazonaws.com/prod",
        "checkUpdateApi":   "https://6at3p6r6ce.execute-api.us-east-2.amazonaws.com/prod",
        "userAccountApi":   "https://6r8m5rxeth.execute-api.us-east-2.amazonaws.com/prod",
        "s3Api":            "https://suk4e76xe5.execute-api.us-east-2.amazonaws.com/prod",
        "iotDomain":        "a3j5zqqo5iuph9-ats.iot.us-east-2.amazonaws.com",
    },
    "ap-east-1": {
        "deviceBindingApi": "https://08ydw34dfj.execute-api.ap-east-1.amazonaws.com/prod",
        "deviceProfileApi": "https://i1pbnu30si.execute-api.ap-east-1.amazonaws.com/prod",
        "checkUpdateApi":   "https://kdueg6qcwl.execute-api.ap-east-1.amazonaws.com/prod",
        "userAccountApi":   "https://1h2q9awtqd.execute-api.ap-east-1.amazonaws.com/prod",
        "s3Api":            "https://m35t3px95i.execute-api.ap-east-1.amazonaws.com/prod",
        "iotDomain":        "a3j5zqqo5iuph9-ats.iot.ap-east-1.amazonaws.com",
    },
}

# ─────────────────────────────────────────────────────────────
# RobotStatus enum — workStatus is an INTEGER in the shadow
# ─────────────────────────────────────────────────────────────
WORK_STATUS_NONE           = 0   # idle / not started
WORK_STATUS_WAITING        = 1   # ready, waiting for command
WORK_STATUS_MOWING         = 2   # CLEANING (mowing)
WORK_STATUS_PAUSE          = 3   # paused mid-mow
WORK_STATUS_DOCKING        = 4   # returning to base
WORK_STATUS_CHARGING       = 5   # charging at station
WORK_STATUS_REMOTE_CONTROL = 6   # manual remote control
WORK_STATUS_ERROR          = 7   # error state
WORK_STATUS_RESUME         = 8   # resuming after pause
WORK_STATUS_ZONE_PARTITION = 9   # zone mapping/partitioning
WORK_STATUS_PAUSE_DOCKING  = 10  # paused while docking
WORK_STATUS_UPDATING       = 11  # OTA firmware update
WORK_STATUS_CHARGING_FULL  = 12  # fully charged
WORK_STATUS_EMERGENCY_STOP = 13  # emergency stop triggered
WORK_STATUS_ESCAPING       = 14  # escaping from stuck position
WORK_STATUS_RTT            = 15  # factory RTT test mode

# Virtual status (not in protobuf enum, set locally when shadow absent)
WORK_STATUS_OFFLINE        = -1

USER_CTRL_RECHARGE_DOCK    = 33   # dock + keep task progress
USER_CTRL_FORCE_REINIT     = 28   # cancel task, stop in place
USER_CTRL_PAUSE_DOCK       = 21   # pause while docking
USER_CTRL_RESUME_DOCK      = 22   # resume docking
USER_CTRL_RESUME           = 4    # resume from pause
USER_CTRL_DOCK                   = 2

# Statuses that map to LawnMowerActivity.MOWING
MOWING_STATUSES    = {WORK_STATUS_MOWING, WORK_STATUS_RESUME, WORK_STATUS_ZONE_PARTITION}
# Statuses that map to LawnMowerActivity.RETURNING
RETURNING_STATUSES = {WORK_STATUS_DOCKING, WORK_STATUS_PAUSE_DOCKING, WORK_STATUS_ESCAPING}
# Statuses that map to LawnMowerActivity.DOCKED
DOCKED_STATUSES    = {WORK_STATUS_NONE, WORK_STATUS_WAITING, WORK_STATUS_CHARGING,
                      WORK_STATUS_CHARGING_FULL, WORK_STATUS_UPDATING}
# Statuses that map to LawnMowerActivity.PAUSED
PAUSED_STATUSES    = {WORK_STATUS_PAUSE, WORK_STATUS_REMOTE_CONTROL}
# Statuses that map to LawnMowerActivity.ERROR
ERROR_STATUSES     = {WORK_STATUS_ERROR, WORK_STATUS_EMERGENCY_STOP}

# ─────────────────────────────────────────────────────────────
# RtkStatus enum — rtkStatus is an INTEGER
# ─────────────────────────────────────────────────────────────
RTK_STATUS_NOT_READY  = 0  # RTK_NOT_REDAY (sic in source)
RTK_STATUS_FLOAT_FIX  = 1  # RTK_FLOAT_FIX (~40 cm precision)
RTK_STATUS_FIX        = 2  # RTK_FIX (~2 cm precision)

RTK_STATUS_LABELS = {
    RTK_STATUS_NOT_READY: "Not Ready",
    RTK_STATUS_FLOAT_FIX: "Float Fix",
    RTK_STATUS_FIX:       "Fixed",
}

# ─────────────────────────────────────────────────────────────
# cleanMode STRING values
# ─────────────────────────────────────────────────────────────
CLEAN_MODE_ZIGZAG          = "ZIGZAG_MODE"
CLEAN_MODE_CHESS_BOARD     = "CHESS_BOARD_MODE"
CLEAN_MODE_PERIMETER_ONLY  = "PERIMETER_LAPS_ONLY_MODE"
CLEAN_MODE_ADAPTIVE_ZIGZAG = "ADAPTIVE_ZIGZAG_MODE"

CLEAN_MODE_OPTIONS = [
    CLEAN_MODE_ZIGZAG,
    CLEAN_MODE_CHESS_BOARD,
    CLEAN_MODE_PERIMETER_ONLY,
    CLEAN_MODE_ADAPTIVE_ZIGZAG,
]

# ─────────────────────────────────────────────────────────────
# deviceState STRING (online/offline — separate from workStatus)
# ─────────────────────────────────────────────────────────────
DEVICE_STATE_ONLINE  = "online"
DEVICE_STATE_OFFLINE = "offline"

# ─────────────────────────────────────────────────────────────
# Shadow field names — verified from decompiled APK protobuf defs
# ─────────────────────────────────────────────────────────────

# --- Top-level state ---
F_WORK_STATUS    = "workStatus"       # int  (RobotStatus enum)
F_DEVICE_STATE   = "deviceState"      # str  "online" / "offline"
F_IS_ONLINE      = "isOnline"         # bool
F_IS_CHARGING    = "isCharging"       # bool
F_IS_RECHARGING  = "isRecharging"     # bool (docked and charging)

# --- Battery ---
F_BATTERY        = "battery"          # int  0-100 %

# --- Firmware ---
F_FW_VERSION     = "fwVersion"        # str  app firmware version
F_MCU_VERSION    = "mcuVersion"       # str  MCU firmware version

# --- Mowing ---
F_CUT_HEIGHT     = "cutHeight"        # int  mm  (protobuf / BLE side)
F_CUTTING_HEIGHT = "cuttingHeight"    # int  mm  (cloud shadow side — same value)
F_CLEAN_MODE     = "cleanMode"        # str  (CLEAN_MODE_* constants)
F_CLEAN_AREA     = "cleanArea"        # int  m²  area mowed this session
F_CUT_SPEED      = "cutSpeed"         # int  blade speed

# --- Zones ---
F_CLEAN_ZONE_IDS = "cleanZoneIds"     # list[str]  zones to mow
F_GO_ZONE_ID     = "goZoneHashId"     # str        current target zone
F_GO_ZONE_IDS    = "goZoneHashIds"    # list[str]  queued target zones
F_CUT_ZONE_ID    = "cutZoneHashId"    # str        zone currently being cut
F_NOGO_ZONE_IDS  = "nogoZoneHashIds"  # list[str]  exclusion zones

# --- Errors ---
F_ERROR_CODE     = "errorCode"        # int   primary error code
F_ERROR_CODES    = "errorCodes"       # list[int] all active error codes

# --- RTK / GPS ---
F_RTK_STATUS     = "rtkStatus"        # int  (RtkStatus enum)
F_RTK_L1         = "rtkDiagnosticL1"  # dict {rtkStatus, precision, satelliteCount,
                                      #        l1/l2/l5 SatelliteCount, l1/l2/l5 Snr,
                                      #        baseStationStatus, baseDataErrorRate}
F_RTK_L2         = "rtkDiagnosticL2"  # dict {diffAge, loraBps0/1/2, hwDc0/1/2,
                                      #        cwRatio0/1/2, antValue0/1/2}

# --- Connectivity (nested inside netDetailInfo) ---
F_NET_DETAIL     = "netDetailInfo"    # dict — keys below:
#   netDetailInfo sub-keys:
NET_CURRENT_NET      = "currentNet"       # int  0=none 1=WiFi 2=LTE
NET_WIFI_NAME        = "wifiName"         # str
NET_WIFI_IP          = "wifiIp"           # str
NET_WIFI_SIGNAL      = "wifiSignal"       # int  dBm
NET_SIM_CARD_STATUS  = "simCardStatus"    # int  (SimCardStatus enum)
NET_SIM_IP           = "simIp"            # str
NET_SIM_SIGNAL       = "simSignal"        # int  dBm
NET_SIM_REGISTRATION = "simRegistration"  # int  (SimCardRegist enum)
NET_SIM_CONNECTION   = "simConnection"    # bool
NET_SIM_ICCID        = "simIccid"         # str

# Signal quality (top-level, from protobuf BLE messages)
F_WIFI_SIGNAL    = "wifiSignalQuality"  # int
F_LTE_SIGNAL     = "lteSignalQuality"   # int
F_BT_SIGNAL      = "btSignalQuality"    # int
F_LTE_WORKING    = "lteWorking"         # bool
F_WIFI_WORKING   = "wifiWorking"        # bool

# --- Map ---
F_OBS_MAP        = "obsMap"             # dict  obstacle/boundary map data
F_MAP_AREA       = "mapArea"            # area of the mapped lawn

# --- Motion ---
F_LINEAR_SPEED   = "linearSpeed"        # float
F_ANGULAR_SPEED  = "angularSpeed"       # float

# ─────────────────────────────────────────────────────────────
# Known error codes (partial — at least 84 codes in the app)
# ─────────────────────────────────────────────────────────────
ERROR_CODES: dict[int, tuple[str, str]] = {
     1: ("ERROR_WHEEL_DRIVE_MALFUNCTION", "Wheel Motor Error"),
     2: ("ERROR_WHEEL_TEMP_ABN", "Motor Overheat"),
     3: ("ERROR_WHEEL_DRIVE_MALFUNCTION", "Wheel Motor Error"),
     7: ("ERROR_FIRST_LIFT_BLOCKED", "Lifting Motor Jammed"),
    10: ("ERROR_BLADE_COMM_LOST", "Blade Motor Error"),
    13: ("ERROR_LOC_VIO_FAILED", "Navigation Internal Error"),
    15: ("ERROR_LOC_INIT_RTK_NOT_FIX", "Weak RTK Signal"),
    16: ("ERROR_LOC_INIT_TIMEOUT", "Location Service Init Timeout"),
    17: ("ERROR_ROBOT_CLIFF", "Unsafe Drop Detected"),
    18: ("ERROR_ROBOT_INCLINE", "Excessive Tilt Detected"),
    19: ("ERROR_ROBOT_SLIP", "Slipping Detected"),
    20: ("ERROR_ROBOT_OUT_OF_MAP", "Out of Bounds"),
    21: ("ERROR_ROBOT_STUCK", "Mower Stuck"),
    25: ("ERROR_MAP_NO_DOCK", "Charging Station not Detected"),
    27: ("ERROR_MAP_ZERO_GO_ZONES", "No Available Mowing Zone"),
    28: ("ERROR_MAP_ZONE_UNREACHABLE", "Zone Not Reachable"),
    29: ("ERROR_DOCK_NOT_FOUND", "Charging Station Tag Not Detected"),
    30: ("ERROR_DOCK_ERROR", "Docking Failed"),
    31: ("ERROR_LOW_BATTERY", "Battery Low"),
    32: ("ERROR_SENSOR_CAMERA", "Camera Signal Lost"),
    33: ("ERROR_SENSOR_IMU0", "IMU Signal Lost"),
    34: ("ERROR_SENSOR_GNSS", "GPS Signal Lost"),
    44: ("ERROR_BUMPER_STUCK", "Bumper Jammed"),
    45: ("ERROR_BLADE_STUCK", "Blade Jammed"),
    46: ("ERROR_LOC_COMM_LOST", "Location Service Unstable"),
    50: ("ERROR_PP_CHANNEL_ERROR", "Navigation Internal Error"),
    51: ("ERROR_PP_DOCK_SIGNAL_LOST", "Charging Not Detected"),
    52: ("ERROR_PP_DOCK_PATH_NOT_FOUND", "Charging Station Not Reachable"),
    53: ("ERROR_PP_CHANNEL_ERROR", "Navigation Internal Error"),
    58: ("ERROR_BASE_STATION_INVALID", "Charging Station Placement Issue"),
    61: ("ERROR_LOC_RTK_BASE", "No ENU Base Point from RTK Base Station"),
    64: ("ERROR_ROBOT_OUT_OF_MAP", "Out of Bounds"),
    65: ("ERROR_ROBOT_OUT_OF_MAP", "Out of Bounds"),
    66: ("ERROR_ROBOT_STUCK", "Mower Stuck"),
    67: ("ERROR_PP_CHANNEL_ERROR", "Navigation Internal Error"),
    68: ("ERROR_PP_CHANNEL_ERROR", "Navigation Internal Error"),
    69: ("ERROR_PP_CHANNEL_ERROR", "Navigation Internal Error"),
    70: ("ERROR_PP_CHANNEL_ERROR", "Navigation Internal Error"),
    71: ("ERROR_PP_CHANNEL_ERROR", "Navigation Internal Error"),
    72: ("ERROR_CMD_WHEEL_SPD_INCOMPATIBLE", "Wheel Motor Control Fault"),
    73: ("ERROR_LOC_VIO_FAILED", "Navigation Internal Error"),
    74: ("ERROR_CHANNEL_BUMPER", "Channel Obstacle Detected"),
    75: ("ERROR_CHANNEL_BUMPER", "Channel Obstacle Detected"),
    76: ("ERROR_EDGE_FOLLOW_OBS", "Perimeter Obstacle Detected"),
    77: ("ERROR_EDGE_FOLLOW_OBS", "Perimeter Obstacle Detected"),
    79: ("ERROR_LOC_VIO_FAILED", "Navigation Internal Error"),
    80: ("ERROR_DOCK_NOT_FOUND", "Charging Station Tag Not Detected"),
    81: ("ERROR_LOC_EDGE_SCORE_LOW", "Weak RTK Signal"),
    82: ("ERROR_LOC_EDGE_SCORE_LOW", "Weak RTK Signal"),
    83: ("ERROR_CHANNEL_SLIP", "Slipping on the Channel"),
    84: ("ERROR_ROBOT_SLIP", "Slipping Detected"),
}


def error_label(code: int) -> str:
    """Friendly label for an error code; fallback to E<N> for unknown."""
    entry = ERROR_CODES.get(code)
    if entry:
        return entry[1]
    return f"E{code}"


# Backwards-compat alias for existing callers that imported ERROR_CODE_LABELS
# as a code->label dict. Derived from ERROR_CODES.
ERROR_CODE_LABELS: dict[int, str] = {code: lbl for code, (_, lbl) in ERROR_CODES.items()}


# WarningCode enum — full table recovered from the Lymow app 3.0.7 Hermes bytecode
# (hermes-dec disassembly). {code: (ENUM_NAME, friendly_label)}.
WARNING_CODES: dict[int, tuple[str, str]] = {
    0:  ("WARNING_NONE", "None"),
    1:  ("WARNING_WHEEL_OVER_CURRENT", "Wheel Over-Current"),
    2:  ("WARNING_WHEEL_OVER_VOLTAGE", "Wheel Over-Voltage"),
    3:  ("WARNING_WHEEL_UNDER_VOLTAGE", "Wheel Under-Voltage"),
    4:  ("WARNING_BAT_CURRENT_ABN", "Battery Current Abnormal"),
    5:  ("WARNING_FIRST_LIFT_TIMEOUT", "First Lift Timeout"),
    6:  ("WARNING_SECOND_LIFT_TIMEOUT", "Second Lift Timeout"),
    7:  ("WARNING_FRONT_ULTRA_LOST", "Front Ultrasonic Lost"),
    8:  ("WARNING_BACK_ULTRA_LOST", "Rear Ultrasonic Lost"),
    9:  ("WARNING_SOC_COMM_ABN", "SOC Comm Abnormal"),
    10: ("WARNING_MCU_THREAD_SCHEDULE_ABN", "MCU Thread Schedule Abnormal"),
    11: ("WARNING_BLADE_OVER_TEMP", "Blade Over-Temperature"),
    12: ("WARNING_BLADE_OVER_CURRENT", "Blade Over-Current"),
    13: ("WARNING_BLADE_COMM_ABN", "Blade Comm Abnormal"),
    14: ("WARNING_LOC_IGNORE_CMD", "Localization Ignoring Command"),
    15: ("WARNING_LOC_INIT_FAILED", "Localization Init Failed"),
    16: ("WARNING_LOC_INVALID_SENSOR_DATA", "Invalid Localization Sensor Data"),
    17: ("WARNING_LOC_CAMERA_BLOCK", "Localization Camera Blocked"),
    18: ("WARNING_LOC_CAMERA_DATA_UNSYNC", "Localization Camera Data Unsynced"),
    19: ("WARNING_LOC_RTK_SIGNAL_BAD", "RTK Signal Poor"),
    20: ("WARNING_LOC_TEXTURE_WEAK", "Visual Texture Weak"),
    21: ("WARNING_LOC_VIO_ABN", "Visual Odometry Abnormal"),
    22: ("WARNING_LOC_EKF_ABN", "EKF Fusion Abnormal"),
    23: ("WARNING_SEG_LOW_LIGHT", "Segmentation Low Light"),
    24: ("WARNING_ROBOT_ESCAPING", "Robot Escaping"),
    25: ("WARNING_MCU_COMM_ABN", "MCU Comm Abnormal"),
    26: ("WARNING_SENSOR_CAMERA_TEMP_ABN", "Camera Temperature Abnormal"),
    27: ("WARNING_SENSOR_CAMERA_ABN", "Camera Sensor Abnormal"),
    28: ("WARNING_SENSOR_IMU0_ABN", "IMU Sensor Abnormal"),
    29: ("WARNING_SENSOR_GNSS_ABN", "GNSS Sensor Abnormal"),
    30: ("WARNING_ROBOT_SLIP", "Wheel Slip Detected"),
    31: ("WARNING_LOC_COMM_ABN", "Localization Comm Abnormal"),
    32: ("WARNING_BLADE_STUCK", "Blade Stuck"),
    33: ("WARNING_SEG_COMM_ABN", "Segmentation Comm Abnormal"),
    34: ("WARING_PP_LATERAL_ERROR_LARGE", "Path Lateral Error Large"),
    35: ("WARNING_LOC_LOW_LIGHT", "Localization Low Light"),
    36: ("WARING_PP_EXECUTION", "Path Execution Warning"),
    37: ("WARNING_ZONE_NOT_CONNECTED", "Zone Not Connected"),
    38: ("WARNING_ZONE_END_FAR_FROM_START", "Zone End Far From Start"),
    39: ("WARNING_ZONE_AREA_TOO_SMALL", "Zone Area Too Small"),
    40: ("WARNING_NO_GO_NOT_IN_ZONE", "No-Go Not Inside Zone"),
    41: ("WARNING_CHANNEL_START_NOT_IN_ZONE", "Channel Start Not In Zone"),
    42: ("WARNING_ONLY_ONE_DOCKING_CHANNEL_ALLOWED", "Only One Docking Channel Allowed"),
    43: ("WARNING_ZONE_EIGHT_PATH", "Zone Figure-Eight Path"),
    44: ("WARNING_MODIFY_ZONE_FAR_FROM_EDGE", "Modified Zone Far From Edge"),
    45: ("WARNING_MODIFY_ZONE_START_CLOSE_END", "Modified Zone Start Close To End"),
    46: ("WARNING_MODIFY_ZONE_CHANGE_CHANNEL_POINT", "Modified Zone Changed Channel Point"),
    47: ("WARNING_MODIFY_ZONE_INTERNAL_FAIL", "Modified Zone Internal Failure"),
    48: ("WARNING_CAN_NOT_FIND_OBJECTS", "Cannot Find Objects"),
    49: ("WARNING_ADD_DOCKING_CHANNEL", "Add Docking Channel"),
    50: ("WARNING_DOCKING_CHANNEL_UNNECESSARY", "Docking Channel Unnecessary"),
    51: ("WARNING_LOC_NO_RTK_BASE", "No RTK Base Station"),
    52: ("WARNING_RTK_BIND_FAIL", "RTK Bind Failed"),
    53: ("WARNING_BASE_STATION_INVALID", "Base Station Invalid"),
    54: ("WARNING_LOC_YAW_ABN", "Heading (Yaw) Abnormal"),
    55: ("WARNING_NOGO_ZONE_ILLEGAL", "No-Go Zone Illegal"),
    56: ("WARNING_SCHEDULE_MODIFY", "Schedule Modified"),
    57: ("WARNING_NOT_ENOUGH_INTERSECT", "Not Enough Intersection"),
    58: ("WARNING_MAP_OPERATE_FAIL", "Map Operation Failed"),
    59: ("WARNING_DIVIDE_NARROW_PART", "Divide: Narrow Part"),
    60: ("WARNING_DIVIDE_AREA_SMALL", "Divide: Area Too Small"),
    61: ("WARNING_CHARGE_STATION_INVALID", "Charge Station Invalid"),
    62: ("WARNING_ZONE_NOT_OVERLAPPED", "Zone Not Overlapped"),
    63: ("WARNING_CODE_MAX", "Max"),
}


def warning_label(code: int) -> str:
    """Friendly label for a warning code; fallback to W<N> for unknown."""
    entry = WARNING_CODES.get(code)
    if entry:
        return entry[1]
    return f"W{code}"


# AudioId enum — the robot's voice-prompt vocabulary (PbOutput.audioId, field 21),
# recovered from app 3.0.7 bytecode. The mower broadcasts which prompt it's playing,
# so this surfaces real-world events (slip, blade-stuck, cliff, theft, etc.) that
# aren't otherwise in telemetry. {code: friendly_label}.
AUDIO_ID_LABELS: dict[int, str] = {
    0:  "None",
    1:  "Power On",
    2:  "Power Off",
    3:  "Mowing",
    4:  "Mowing Paused",
    5:  "Mowing Resumed",
    6:  "Docking",
    7:  "Docking Paused",
    8:  "Wheel Slip",
    9:  "Blade Stuck",
    10: "Battery Low",
    11: "Initialization Failed",
    12: "WiFi Connected",
    13: "WiFi Connect Timeout",
    14: "WiFi Connect Failed",
    15: "User Binding Success",
    16: "User Binding Failed",
    17: "Firmware Update Start",
    18: "Firmware Update Success",
    19: "Firmware Update Failed",
    20: "Bluetooth Pairing",
    21: "Factory RTT Mode",
    22: "Dock Failed",
    23: "Factory Test Mode",
    24: "Cliff Detected",
    25: "Slope Detected",
    26: "Internal Error",
    27: "Robot Locked",
    28: "Charging Started",
    29: "Rain Resume",
    30: "Stop Button Pressed",
    31: "Theft Alarm",
    32: "Cutting Started",
    33: "Max",
}


def audio_label(code: int) -> str:
    """Friendly label for an audio-prompt id; fallback to Audio<N>."""
    return AUDIO_ID_LABELS.get(code, f"Audio {code}")


def audio_event_type(code: int) -> str:
    """Stable event_type slug for an audio id (e.g. 9 -> 'blade_stuck')."""
    return audio_label(code).lower().replace(" ", "_")


# Event types an audio-prompt EventEntity may fire (excludes None/Max sentinels).
AUDIO_EVENT_TYPES: list[str] = [
    audio_event_type(c) for c in AUDIO_ID_LABELS if c not in (0, 33)
]

# ─────────────────────────────────────────────────────────────
# Services
# ─────────────────────────────────────────────────────────────
SERVICE_START_ZONE   = "start_zone"
SERVICE_SET_BLADE    = "set_blade_height"
SERVICE_SET_SCHEDULE = "set_schedule"

# ─────────────────────────────────────────────────────────────
# Lift sensor — verified from APK protobuf enums
# ─────────────────────────────────────────────────────────────
# ERROR_FIRST_LIFT_BLOCKED  = 7  → appears in errorCodes[]
# ERROR_SECOND_LIFT_BLOCKED = 8  → appears in errorCodes[]
# WARNING_FIRST_LIFT_TIMEOUT  = 5 → appears in warningCodes[]
# WARNING_SECOND_LIFT_TIMEOUT = 6 → appears in warningCodes[]
# BLE-only signals (not in cloud shadow): SIGNAL_ONE_CLICK_LIFT,
# SIGNAL_MCU_LIFT_LITTLE, SIGNAL_MCU_RESTORE_LIFT
LIFT_ERROR_CODES   = {7, 8}  # robot lifted or lift mechanism blocked
LIFT_WARNING_CODES = {5, 6}  # lift timeout warnings

# warningCodes is a separate list from errorCodes in the protobuf message
F_WARNING_CODES = "warningCodes"   # list[int]

# ─────────────────────────────────────────────────────────────
# fwVersion protobuf object (nested in shadow — BLE/device info)
# Fields verified from APK protobuf encoder/decoder
# ─────────────────────────────────────────────────────────────
# The app builds the RTSP camera URL as:
#   deviceProfile.ipAddress + ":10022/h264ESVideoTest"
# ipAddress comes from fwVersion.ipAddress in the shadow.
F_FW_DATA    = "fwVersion"     # nested dict (fwVersion protobuf object)
F_IP_ADDRESS = "ipAddress"     # str  robot's local WiFi IP (inside fwVersion)
F_WIFI_SSID  = "wifiSsid"      # str  connected WiFi SSID (inside fwVersion)
F_MAC        = "macAddress"    # str  robot MAC address (inside fwVersion)
F_SERIAL_NO  = "sn"            # str  robot serial number (inside fwVersion)

RTSP_PORT = 10022
RTSP_PATH = "h264ESVideoTest"

# Current-channel detection buffer (metres). Lymow's channel polygons are coarse
# and thin (3-11 points, some pinched to a triangle), so a strict point-in-
# polygon test misses the mower on fast/straight passes. Treat the mower as "in"
# a channel when it is inside OR within this distance of the polygon, so thin
# corridors are reliable triggers for transit automations (gates/doors). User-
# tunable via the Channel Detection Buffer number; 0 = strict inside only.
DEFAULT_CHANNEL_BUFFER_M = 0.75
