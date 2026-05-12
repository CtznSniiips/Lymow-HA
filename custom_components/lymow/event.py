"""Lymow event platform — mowing session completed events.

Fires a `lymow_session_completed` event in the HA event bus (and
records it to the logbook / timeline) whenever a new mowing session
appears in the clean history.

Event data:
  start_time   : ISO-8601 UTC start of the session
  area_m2      : area mowed (m²)
  duration_s   : duration (seconds)
  used_battery : battery % consumed
  end_type     : "completed" | "cancelled" | "unknown"
  zones        : list of zone IDs mowed

The EventEntity (Platform.EVENT, HA 2023.8+) also exposes the last
event as an entity state so it can be used in automations.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import LymowCoordinator
from .entity_base import LymowEntity

_LOGGER = logging.getLogger(__name__)

# mowEndType enum values (from decompiled.js)
_MOW_END_LABELS = {
    0: "unknown",
    1: "completed",   # MOW_END_100 — task finished 100%
    2: "cancelled",   # MOW_END_USER_CANCEL
}


def _parse_session(entry: dict) -> dict[str, Any]:
    """Convert a raw clean_history entry to a flat event data dict."""
    clean_info = entry.get("cleanInfo") or entry.get("clean_info") or {}
    area        = clean_info.get("cleanArea") or clean_info.get("clean_area") or entry.get("clean_area")
    duration    = clean_info.get("cleanTime")  or clean_info.get("clean_time")  or entry.get("clean_time")
    start_ts    = entry.get("cleanStartTime")  or entry.get("clean_start_time") or entry.get("start_time")
    end_type    = _MOW_END_LABELS.get(entry.get("mowEndType", 0), "unknown")
    used_bat    = entry.get("usedBattery") or entry.get("used_battery")
    zones       = (clean_info.get("areaInfo") or {}).get("cleanZoneIds") or entry.get("clean_zone_ids") or []

    start_iso = None
    if start_ts:
        try:
            start_iso = datetime.fromtimestamp(int(start_ts), UTC).isoformat()
        except Exception:
            start_iso = str(start_ts)

    return {
        "start_time":    start_iso,
        "area_m2":       round(float(area), 1) if area is not None else None,
        "duration_s":    int(duration) if duration is not None else None,
        "used_battery":  int(used_bat) if used_bat is not None else None,
        "end_type":      end_type,
        "zones":         zones,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: LymowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LymowSessionEvent(coord)], update_before_add=False)


class LymowSessionEvent(LymowEntity, EventEntity):
    """Event entity that fires when a mowing session completes.

    HA EventEntity requirements:
    - _attr_event_types : list of possible event type strings
    - _trigger_event()  : called to fire and record an event
    """

    _attr_name         = "Last Session"
    _attr_icon         = "mdi:history"
    _attr_event_types  = ["lymow_session_completed"]

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "session_event")
        self._last_session_ts: int | None = None   # tracks last seen cleanStartTime

    def _handle_coordinator_update(self) -> None:
        """Called by HA on every coordinator data update."""
        history: list[dict] = (self.coordinator.data or {}).get("cleanHistory") or []
        if not history:
            super()._handle_coordinator_update()
            return

        # History is newest-first; take the most recent entry.
        latest = history[0]
        ts = latest.get("cleanStartTime") or latest.get("clean_start_time") or latest.get("start_time")
        try:
            ts_int = int(ts) if ts is not None else None
        except (TypeError, ValueError):
            ts_int = None

        if ts_int is not None and ts_int != self._last_session_ts:
            self._last_session_ts = ts_int
            event_data = _parse_session(latest)
            _LOGGER.debug(
                "Lymow new session detected for %s: %s",
                self.coordinator.thing_name,
                event_data,
            )
            self._trigger_event("lymow_session_completed", event_data)

        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose last session summary alongside the event state."""
        history: list[dict] = (self.coordinator.data or {}).get("cleanHistory") or []
        if not history:
            return {}
        return _parse_session(history[0])