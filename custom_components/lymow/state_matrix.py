"""Lawn-mower state decision matrix.

Lookup table: (work_status, robot_status, is_recharging) →
(activity, button-actions as userCtrl ints).

First match wins — place more-specific rows first.
None in a match column = wildcard.

Pure module — no homeassistant imports — unit-testable without HA stubs.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── userCtrl constants ────────────────────────────────────────────────────────
from .protocol import (
    USER_CTRL_CLEAN,
    USER_CTRL_PAUSE,
    USER_CTRL_PAUSE_DOCK,
    USER_CTRL_RECHARGE_DOCK,
    USER_CTRL_RESUME,
    USER_CTRL_RESUME_DOCK,
)
from .const import (
    WORK_STATUS_CHARGING,
    WORK_STATUS_CHARGING_FULL,
    WORK_STATUS_DOCKING,
    WORK_STATUS_EMERGENCY_STOP,
    WORK_STATUS_ERROR,
    WORK_STATUS_ESCAPING,
    WORK_STATUS_MOWING,
    WORK_STATUS_NONE,
    WORK_STATUS_PAUSE,
    WORK_STATUS_PAUSE_DOCKING,
    WORK_STATUS_RESUME,
    WORK_STATUS_WAITING,
    WORK_STATUS_ZONE_PARTITION,
)
ACTIVITY_MOWING    = "mowing"
ACTIVITY_PAUSED    = "paused"
ACTIVITY_DOCKED    = "docked"
ACTIVITY_RETURNING = "returning"
ACTIVITY_ERROR     = "error"


@dataclass(frozen=True, kw_only=True, slots=True)
class StateRow:
    """One matrix row.

    Match columns (None = wildcard):
      work_status   — from data["workStatus"]
      robot_status  — from data["robotStatus"]
      is_recharging — from data["isRecharging"]

    Outcome columns:
      activity      — LawnMowerActivity string (None = "Unknown")
      start_mowing  — userCtrl published on async_start_mowing (None = hide button)
      pause         — userCtrl published on async_pause         (None = hide button)
      dock          — userCtrl published on async_dock          (None = hide button)
      note          — free-form rationale
    """

    work_status: int | None = None
    robot_status: int | None = None
    is_recharging: bool | None = None
    activity: str | None = None
    start_mowing: int | None = None
    pause: int | None = None
    dock: int | None = None
    note: str = ""


STATE_MATRIX: list[StateRow] = [

    # ── 1. Physical errors (robot_status is authoritative) ────────────────
    StateRow(
        robot_status=WORK_STATUS_ERROR,
        activity=ACTIVITY_ERROR,
        pause=USER_CTRL_PAUSE,
        note="rs=ERROR — Pause doubles as Clear Error",
    ),
    StateRow(
        work_status=WORK_STATUS_ERROR,
        activity=ACTIVITY_ERROR,
        pause=USER_CTRL_PAUSE,
        note="ws=ERROR fallback",
    ),
    StateRow(
        robot_status=WORK_STATUS_EMERGENCY_STOP,
        activity=ACTIVITY_ERROR,
        note="rs=EMERGENCY_STOP — no buttons, user must reset on mower",
    ),
    StateRow(
        work_status=WORK_STATUS_EMERGENCY_STOP,
        activity=ACTIVITY_ERROR,
        note="ws=EMERGENCY_STOP — same",
    ),

    # ── 2. Physical pause is authoritative over task intent ───────────────
    StateRow(
        robot_status=WORK_STATUS_PAUSE,
        activity=ACTIVITY_PAUSED,
        start_mowing=USER_CTRL_RESUME,
        dock=USER_CTRL_RECHARGE_DOCK,
        note="rs=PAUSE — Start=RESUME(4), Dock keeps progress",
    ),
    StateRow(
        robot_status=WORK_STATUS_PAUSE_DOCKING,
        activity=ACTIVITY_PAUSED,
        start_mowing=USER_CTRL_RESUME_DOCK,
        note="rs=PAUSE_DOCKING — Start=RESUME_DOCK(22)",
    ),
    StateRow(
        work_status=WORK_STATUS_PAUSE,
        activity=ACTIVITY_PAUSED,
        start_mowing=USER_CTRL_RESUME,
        dock=USER_CTRL_RECHARGE_DOCK,
        note="ws=PAUSE — mirror of rs=PAUSE",
    ),
    StateRow(
        work_status=WORK_STATUS_PAUSE_DOCKING,
        activity=ACTIVITY_PAUSED,
        start_mowing=USER_CTRL_RESUME_DOCK,
        note="ws=PAUSE_DOCKING — mirror",
    ),

    # ── 3. Charging — fork on isRecharging (saved task vs idle) ──────────
    StateRow(
        robot_status=WORK_STATUS_CHARGING,
        is_recharging=True,
        activity=ACTIVITY_DOCKED,
        start_mowing=USER_CTRL_RESUME,
        note="CHARGING + saved task → Start RESUMES",
    ),
    StateRow(
        robot_status=WORK_STATUS_CHARGING_FULL,
        is_recharging=True,
        activity=ACTIVITY_DOCKED,
        start_mowing=USER_CTRL_RESUME,
        note="CHARGING_FULL + saved task → Start RESUMES",
    ),
    StateRow(
        robot_status=WORK_STATUS_CHARGING,
        activity=ACTIVITY_DOCKED,
        start_mowing=USER_CTRL_CLEAN,
        note="CHARGING idle → fresh CLEAN(1)",
    ),
    StateRow(
        robot_status=WORK_STATUS_CHARGING_FULL,
        activity=ACTIVITY_DOCKED,
        start_mowing=USER_CTRL_CLEAN,
        note="CHARGING_FULL idle → fresh CLEAN(1)",
    ),

    # ── 4. Active mowing states ───────────────────────────────────────────
    StateRow(
        work_status=WORK_STATUS_MOWING,
        activity=ACTIVITY_MOWING,
        pause=USER_CTRL_PAUSE,
        dock=USER_CTRL_RECHARGE_DOCK,
        note="ws=MOWING — Pause(3), Dock-keep(33)",
    ),
    StateRow(
        work_status=WORK_STATUS_RESUME,
        activity=ACTIVITY_MOWING,
        pause=USER_CTRL_PAUSE,
        dock=USER_CTRL_RECHARGE_DOCK,
        note="ws=RESUME — transient, treat as MOWING",
    ),
    StateRow(
        work_status=WORK_STATUS_ZONE_PARTITION,
        activity=ACTIVITY_MOWING,
        pause=USER_CTRL_PAUSE,
        dock=USER_CTRL_RECHARGE_DOCK,
        note="ws=ZONE_PARTITION — perimeter cut, treat as MOWING",
    ),
    StateRow(
        work_status=WORK_STATUS_ESCAPING,
        activity=ACTIVITY_MOWING,
        pause=USER_CTRL_PAUSE,
        dock=USER_CTRL_RECHARGE_DOCK,
        note="ws=ESCAPING — recovering from obstacle, still active",
    ),

    # ── 5. Returning to dock ──────────────────────────────────────────────
    StateRow(
        work_status=WORK_STATUS_DOCKING,
        activity=ACTIVITY_RETURNING,
        pause=USER_CTRL_PAUSE_DOCK,
        note="ws=DOCKING — Pause sends PAUSE_DOCK(21)",
    ),

    # ── 6. Idle ───────────────────────────────────────────────────────────
    StateRow(
        work_status=WORK_STATUS_WAITING,
        activity=ACTIVITY_DOCKED,
        start_mowing=USER_CTRL_CLEAN,
        note="ws=WAITING idle → fresh CLEAN(1)",
    ),
    StateRow(
        work_status=WORK_STATUS_NONE,
        activity=ACTIVITY_DOCKED,
        start_mowing=USER_CTRL_CLEAN,
        note="ws=NONE idle → fresh CLEAN(1)",
    ),

    # ── 7. Catch-all (UPDATING, RTT, REMOTE_CONTROL, unhandled) ──────────
]

DEFAULT_ROW = StateRow(
    activity=None,
    note="default — unhandled combo; HA shows Unknown, no buttons",
)


def lookup(
    *, work_status: int, robot_status: int, is_recharging: bool
) -> StateRow:
    """Return first matching row, or DEFAULT_ROW."""
    for row in STATE_MATRIX:
        if row.work_status   is not None and row.work_status   != work_status:
            continue
        if row.robot_status  is not None and row.robot_status  != robot_status:
            continue
        if row.is_recharging is not None and row.is_recharging != is_recharging:
            continue
        return row
    return DEFAULT_ROW


def features_for(row: StateRow):
    """Return LawnMowerEntityFeature flags from populated action columns."""
    from homeassistant.components.lawn_mower import LawnMowerEntityFeature
    f = LawnMowerEntityFeature(0)
    if row.start_mowing is not None:
        f |= LawnMowerEntityFeature.START_MOWING
    if row.pause        is not None:
        f |= LawnMowerEntityFeature.PAUSE
    if row.dock         is not None:
        f |= LawnMowerEntityFeature.DOCK
    return f