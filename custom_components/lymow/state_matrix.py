"""Lymow lawn-mower state/action decision matrix.

Pure module, no Home Assistant imports. It maps physical/task status to:
  - HA activity string
  - which userCtrl to send for Start/Pause/Dock

Robot status is treated as physical truth where it can disagree with workStatus.
"""
from __future__ import annotations

from dataclasses import dataclass

# userCtrl values
USER_CTRL_CLEAN = 1
USER_CTRL_DOCK = 2
USER_CTRL_PAUSE = 3
USER_CTRL_RESUME = 4
USER_CTRL_PAUSE_DOCK = 21
USER_CTRL_RESUME_DOCK = 22
USER_CTRL_RECHARGE_DOCK = 33

# workStatus / robotStatus values observed in Lymow firmware
WORK_STATUS_NONE = 0
WORK_STATUS_WAITING = 1
WORK_STATUS_MOWING = 2
WORK_STATUS_PAUSE = 3
WORK_STATUS_DOCKING = 4
WORK_STATUS_CHARGING = 5
WORK_STATUS_REMOTE_CONTROL = 6
WORK_STATUS_ERROR = 7
WORK_STATUS_RESUME = 8
WORK_STATUS_ZONE_PARTITION = 9
WORK_STATUS_PAUSE_DOCKING = 10
WORK_STATUS_UPDATING = 11
WORK_STATUS_CHARGING_FULL = 12
WORK_STATUS_EMERGENCY_STOP = 13
WORK_STATUS_ESCAPING = 14

ACTIVITY_MOWING = "mowing"
ACTIVITY_PAUSED = "paused"
ACTIVITY_DOCKED = "docked"
ACTIVITY_RETURNING = "returning"
ACTIVITY_ERROR = "error"


@dataclass(frozen=True, kw_only=True, slots=True)
class StateRow:
    work_status: int | None = None
    robot_status: int | None = None
    is_recharging: bool | None = None
    activity: str | None = None
    start_mowing: int | None = None
    pause: int | None = None
    dock: int | None = None
    note: str = ""


STATE_MATRIX: list[StateRow] = [
    # Physical errors override task intent.
    StateRow(robot_status=WORK_STATUS_ERROR, activity=ACTIVITY_ERROR, pause=USER_CTRL_PAUSE,
             note="rs=ERROR: pause can clear/acknowledge error"),
    StateRow(work_status=WORK_STATUS_ERROR, activity=ACTIVITY_ERROR, pause=USER_CTRL_PAUSE),
    StateRow(robot_status=WORK_STATUS_EMERGENCY_STOP, activity=ACTIVITY_ERROR,
             note="physical emergency stop, no safe remote action"),
    StateRow(work_status=WORK_STATUS_EMERGENCY_STOP, activity=ACTIVITY_ERROR),

    # Physical pause is authoritative over task intent.
    StateRow(robot_status=WORK_STATUS_PAUSE, activity=ACTIVITY_PAUSED,
             start_mowing=USER_CTRL_RESUME, dock=USER_CTRL_RECHARGE_DOCK),
    StateRow(robot_status=WORK_STATUS_PAUSE_DOCKING, activity=ACTIVITY_PAUSED,
             start_mowing=USER_CTRL_RESUME_DOCK),
    StateRow(work_status=WORK_STATUS_PAUSE, activity=ACTIVITY_PAUSED,
             start_mowing=USER_CTRL_RESUME, dock=USER_CTRL_RECHARGE_DOCK),
    StateRow(work_status=WORK_STATUS_PAUSE_DOCKING, activity=ACTIVITY_PAUSED,
             start_mowing=USER_CTRL_RESUME_DOCK),

    # Charging at dock: if isRecharging=True, a saved task can be resumed.
    StateRow(robot_status=WORK_STATUS_CHARGING, is_recharging=True,
             activity=ACTIVITY_DOCKED, start_mowing=USER_CTRL_RESUME),
    StateRow(robot_status=WORK_STATUS_CHARGING_FULL, is_recharging=True,
             activity=ACTIVITY_DOCKED, start_mowing=USER_CTRL_RESUME),
    StateRow(robot_status=WORK_STATUS_CHARGING,
             activity=ACTIVITY_DOCKED, start_mowing=USER_CTRL_CLEAN),
    StateRow(robot_status=WORK_STATUS_CHARGING_FULL,
             activity=ACTIVITY_DOCKED, start_mowing=USER_CTRL_CLEAN),

    # Active task states.
    StateRow(work_status=WORK_STATUS_MOWING, activity=ACTIVITY_MOWING,
             pause=USER_CTRL_PAUSE, dock=USER_CTRL_RECHARGE_DOCK),
    StateRow(work_status=WORK_STATUS_RESUME, activity=ACTIVITY_MOWING,
             pause=USER_CTRL_PAUSE, dock=USER_CTRL_RECHARGE_DOCK),
    StateRow(work_status=WORK_STATUS_ZONE_PARTITION, activity=ACTIVITY_MOWING,
             pause=USER_CTRL_PAUSE, dock=USER_CTRL_RECHARGE_DOCK),
    StateRow(work_status=WORK_STATUS_ESCAPING, activity=ACTIVITY_MOWING,
             pause=USER_CTRL_PAUSE, dock=USER_CTRL_RECHARGE_DOCK),

    # Returning.
    StateRow(work_status=WORK_STATUS_DOCKING, activity=ACTIVITY_RETURNING,
             pause=USER_CTRL_PAUSE_DOCK),

    # Idle.
    StateRow(work_status=WORK_STATUS_WAITING, activity=ACTIVITY_DOCKED,
             start_mowing=USER_CTRL_CLEAN),
    StateRow(work_status=WORK_STATUS_NONE, activity=ACTIVITY_DOCKED,
             start_mowing=USER_CTRL_CLEAN),
]

DEFAULT_ROW = StateRow(activity=None, note="unhandled state combo")


def lookup(*, work_status: int | None, robot_status: int | None, is_recharging: bool | None) -> StateRow:
    ws = -1 if work_status is None else work_status
    rs = ws if robot_status is None else robot_status
    rech = bool(is_recharging)
    for row in STATE_MATRIX:
        if row.work_status is not None and row.work_status != ws:
            continue
        if row.robot_status is not None and row.robot_status != rs:
            continue
        if row.is_recharging is not None and row.is_recharging != rech:
            continue
        return row
    return DEFAULT_ROW
