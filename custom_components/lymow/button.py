"""Lymow button platform.

Exposes individual command buttons so they can be placed anywhere in
Lovelace independently from the lawn_mower card.

Buttons:
  - Start Mowing    → state-matrix driven (CLEAN or RESUME)
  - Pause           → state-matrix driven (PAUSE or PAUSE_DOCK)
  - Dock            → RECHARGE_DOCK (keep task progress)
  - Cancel Task     → FORCE_REINIT (stop in place, reset to waiting)
  - Dock & Cancel   → DOCK (dock + abandon task)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import state_matrix
from .const import (
    DOMAIN,
    USER_CTRL_DOCK,
    USER_CTRL_FORCE_REINIT,
    USER_CTRL_RECHARGE_DOCK,
)
from .coordinator import LymowCoordinator
from .entity_base import LymowEntity
from .protocol import encode_userctrl

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: LymowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        LymowStartButton(coord),
        LymowPauseButton(coord),
        LymowDockButton(coord),
        LymowCancelTaskButton(coord),
        LymowDockCancelButton(coord),
    ])


# ── Shared base ───────────────────────────────────────────────────────────────

class _LymowButton(LymowEntity, ButtonEntity):
    """Base for all Lymow command buttons."""

    def __init__(self, coordinator: LymowCoordinator, key: str) -> None:
        super().__init__(coordinator, key)

    def _matrix_row(self) -> state_matrix.StateRow:
        d   = self.coordinator.data or {}
        ws  = d.get("workStatus",  0)
        rs  = d.get("robotStatus", 0)
        rch = bool(d.get("isRecharging", False))
        return state_matrix.lookup(
            work_status=ws, robot_status=rs, is_recharging=rch
        )

    def _publish(self, user_ctrl: int) -> None:
        self.coordinator._publish(encode_userctrl(user_ctrl))


# ── Start Mowing ──────────────────────────────────────────────────────────────

class LymowStartButton(_LymowButton):
    """Start or resume mowing — routes via state matrix."""

    _attr_name = "Start Mowing"
    _attr_icon = "mdi:play"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_start")

    async def async_press(self) -> None:
        action = self._matrix_row().start_mowing
        if action is None:
            d = self.coordinator.data or {}
            raise HomeAssistantError(
                f"Cannot start mowing from current state "
                f"(workStatus={d.get('workStatus')}, robotStatus={d.get('robotStatus')})"
            )
        _LOGGER.debug("Lymow Start → userCtrl=%s", action)
        self._publish(action)


# ── Pause ─────────────────────────────────────────────────────────────────────

class LymowPauseButton(_LymowButton):
    """Pause mowing or docking — routes via state matrix."""

    _attr_name = "Pause"
    _attr_icon = "mdi:pause"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_pause")

    async def async_press(self) -> None:
        action = self._matrix_row().pause
        if action is None:
            raise HomeAssistantError("Cannot pause from current state")
        _LOGGER.debug("Lymow Pause → userCtrl=%s", action)
        self._publish(action)


# ── Dock (keep progress) ──────────────────────────────────────────────────────

class LymowDockButton(_LymowButton):
    """Return to dock and KEEP task progress (recharge-resume)."""

    _attr_name = "Dock"
    _attr_icon = "mdi:home-import-outline"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_dock")

    async def async_press(self) -> None:
        _LOGGER.debug("Lymow Dock (keep) → userCtrl=%s", USER_CTRL_RECHARGE_DOCK)
        self._publish(USER_CTRL_RECHARGE_DOCK)


# ── Cancel Task ───────────────────────────────────────────────────────────────

class LymowCancelTaskButton(_LymowButton):
    """Stop in place and reset to waiting (= Cancel task in app)."""

    _attr_name = "Cancel Task"
    _attr_icon = "mdi:cancel"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_cancel_task")

    async def async_press(self) -> None:
        _LOGGER.debug("Lymow Cancel Task → userCtrl=%s", USER_CTRL_FORCE_REINIT)
        self._publish(USER_CTRL_FORCE_REINIT)


# ── Dock & Cancel ─────────────────────────────────────────────────────────────

class LymowDockCancelButton(_LymowButton):
    """Return to dock AND abandon the current task (no resume)."""

    _attr_name = "Dock & Cancel"
    _attr_icon = "mdi:home-remove-outline"

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "btn_dock_cancel")

    async def async_press(self) -> None:
        _LOGGER.debug("Lymow Dock+Cancel → userCtrl=%s", USER_CTRL_DOCK)
        self._publish(USER_CTRL_DOCK)