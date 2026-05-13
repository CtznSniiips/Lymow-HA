"""Lymow Robot Mower integration — MQTT push-driven."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CognitoAuth, LymowClient
from .const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REGION,
    DOMAIN,
    SERVICE_SET_BLADE,
    SERVICE_SET_SCHEDULE,
    SERVICE_START_ZONE,
)
from .coordinator import LymowCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BUTTON,
    Platform.EVENT,
    Platform.LAWN_MOWER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.CAMERA,
    Platform.DEVICE_TRACKER,
    Platform.UPDATE,
    Platform.SWITCH,
    Platform.TIME
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Lymow from a config entry."""
    email      = entry.data[CONF_EMAIL]
    password   = entry.data[CONF_PASSWORD]
    region     = entry.data[CONF_REGION]
    thing_name = entry.data["thing_name"]

    session = async_get_clientsession(hass)
    auth    = CognitoAuth(region, session)

    # Restore stored tokens to avoid re-login on every HA restart
    if entry.data.get("refresh_token"):
        auth.from_dict(entry.data)
        try:
            await auth.ensure_valid(email, password)
        except Exception:
            _LOGGER.warning("Stored tokens invalid for %s — re-logging in", thing_name)
            await auth.login(email, password)
            await auth.get_aws_credentials()
    else:
        await auth.login(email, password)
        await auth.get_aws_credentials()

    client = LymowClient(region, auth, session)

    coordinator = LymowCoordinator(
        hass=hass,
        auth=auth,
        client=client,
        thing_name=thing_name,
        region=region,
        email=email,
        password=password,
    )

    # Store reference so entity platforms can find it
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Connect MQTT and fire startup queries
    await coordinator.async_setup()

    # Static device info (IP for camera, serial, fw version)
    await coordinator.async_refresh_device_info()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_services(hass)

    # Persist updated tokens
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, **auth.to_dict()},
    )

    return True

def _register_services(hass: HomeAssistant) -> None:
    """Register Lymow services — idempotent, registers only once per HA run."""
    from homeassistant.exceptions import HomeAssistantError
    import voluptuous as vol
    from homeassistant.helpers import config_validation as cv, device_registry as dr
    from .protocol import encode_userctrl, encode_start_zones
    from .const import USER_CTRL_RECHARGE_DOCK, USER_CTRL_FORCE_REINIT
 
    if hass.services.has_service(DOMAIN, "start_zones"):
        return
 
    def _get_coordinator(call: ServiceCall) -> LymowCoordinator:
        """Resolve coordinator from call.target.device_id or call.data.device_id."""
        target = getattr(call, "target", None) or {}
        target_ids = (target.get("device_id") if isinstance(target, dict) else None)
        device_id = None
        if target_ids:
            device_id = target_ids if isinstance(target_ids, str) else next(iter(target_ids), None)
        if not device_id:
            di = call.data.get("device_id")
            device_id = di if isinstance(di, str) else (di[0] if isinstance(di, list) and di else None)
        if not device_id:
            # Fallback: pick the first (and usually only) coordinator
            coords = list(hass.data.get(DOMAIN, {}).values())
            if len(coords) == 1:
                return coords[0]
            raise HomeAssistantError(
                "Multiple Lymow devices found — specify a target device."
            )
        device_reg = dr.async_get(hass)
        device = device_reg.async_get(device_id)
        if device:
            for domain, identifier in device.identifiers:
                if domain == DOMAIN:
                    for coord in hass.data.get(DOMAIN, {}).values():
                        if getattr(coord, "thing_name", None) == identifier:
                            return coord
        raise HomeAssistantError("Lymow device not found.")
 
    async def _handle_start_zones(call: ServiceCall) -> None:
        coord = _get_coordinator(call)
        raw_zones = call.data.get("zones", [])
        if isinstance(raw_zones, str):
            raw_zones = [raw_zones]
 
        # Resolve zone names → hashIds
        btmap = (coord.data or {}).get("btMap") or {}
        zones = btmap.get("zones") or []
        name_map = {
            (z.get("name") or "").lower(): z.get("hashId")
            for z in zones if z.get("hashId")
        }
        hash_id_set = {z.get("hashId") for z in zones if z.get("hashId")}
 
        resolved: list[str] = []
        for zid in raw_zones:
            if zid in hash_id_set:
                resolved.append(zid)
            else:
                hid = name_map.get(zid.lower())
                if hid:
                    resolved.append(hid)
                else:
                    raise HomeAssistantError(f"Zone '{zid}' not found in map.")
 
        if not resolved:
            raise HomeAssistantError("No valid zones provided.")
 
        coord._publish(encode_start_zones(resolved))
 
    async def _handle_dock_cancel_task(call: ServiceCall) -> None:
        """Dock AND cancel the current task (no recharge-resume)."""
        coord = _get_coordinator(call)
        coord._publish(encode_userctrl(USER_CTRL_RECHARGE_DOCK))
 
    async def _handle_cancel_task(call: ServiceCall) -> None:
        """Force-reinit: stop in place, reset to waiting ('Cancel task' in app)."""
        coord = _get_coordinator(call)
        coord._publish(encode_userctrl(USER_CTRL_FORCE_REINIT))
 
    hass.services.async_register(
        DOMAIN, "start_zones", _handle_start_zones,
        schema=vol.Schema({
            vol.Optional("device_id"): vol.Any(str, [str]),
            vol.Required("zones"):     vol.Any(str, [str]),
        }),
    )
    hass.services.async_register(
        DOMAIN, "dock_cancel_task", _handle_dock_cancel_task,
        schema=vol.Schema({vol.Optional("device_id"): vol.Any(str, [str])}),
    )
    hass.services.async_register(
        DOMAIN, "cancel_task", _handle_cancel_task,
        schema=vol.Schema({vol.Optional("device_id"): vol.Any(str, [str])}),
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: LymowCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator:
        await coordinator.async_shutdown()

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded