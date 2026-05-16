"""Lymow event platform — mowing session completed events."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import LymowCoordinator
from .entity_base import LymowEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coord: LymowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LymowSessionEvent(coord)], update_before_add=False)


class LymowSessionEvent(LymowEntity, EventEntity):
    """Event entity that fires when a mowing session completes."""

    _attr_name = "Last Session"
    _attr_icon = "mdi:history"
    _attr_event_types = ["lymow_session_completed"]

    def __init__(self, coordinator: LymowCoordinator) -> None:
        super().__init__(coordinator, "session_event")
        self._last_event_id: int | str | None = None

    def _handle_coordinator_update(self) -> None:
        """Called by HA on every coordinator data update."""
        data = self.coordinator.data or {}

        event_data = data.get("lastSessionEvent")
        event_id = data.get("lastSessionEventId")

        if isinstance(event_data, dict) and event_id is not None:
            if event_id != self._last_event_id:
                self._last_event_id = event_id

                _LOGGER.debug(
                    "Lymow session event triggered for %s: %s",
                    self.coordinator.thing_name,
                    event_data,
                )

                self._trigger_event(
                    "lymow_session_completed",
                    event_data,
                )

        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose last session summary alongside the event state."""
        data = self.coordinator.data or {}
        event_data = data.get("lastSessionEvent")

        if isinstance(event_data, dict):
            return event_data

        return {}