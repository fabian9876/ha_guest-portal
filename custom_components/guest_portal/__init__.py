"""HA Guest Portal integration entry point.

Version 0.1.0 provides configuration and a manual alone-mode service.
Guest authentication and entity proxying are intentionally not implemented yet.
"""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry

from .const import (
    ATTR_ENABLED,
    DOMAIN,
    EVENT_ALONE_MODE_CHANGED,
    SERVICE_SET_ALONE_MODE,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = []


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {"entries": {}})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a configured entry."""
    domain_data = hass.data.setdefault(DOMAIN, {"entries": {}})
    entry_data = {"alone_mode": False}
    domain_data["entries"][entry.entry_id] = entry_data

    async def async_set_alone_mode(call: ServiceCall) -> None:
        """Manually enable or disable alone mode."""
        enabled = call.data[ATTR_ENABLED]
        entry_data["alone_mode"] = enabled
        hass.bus.async_fire(
            EVENT_ALONE_MODE_CHANGED,
            {"entry_id": entry.entry_id, "enabled": enabled, "source": "service"},
        )
        _LOGGER.info("Alone mode %s", "enabled" if enabled else "disabled")

    if not hass.services.has_service(DOMAIN, SERVICE_SET_ALONE_MODE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_ALONE_MODE,
            async_set_alone_mode,
            schema=vol.Schema({vol.Required(ATTR_ENABLED): bool}),
        )

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    domain_data = hass.data.get(DOMAIN, {})
    domain_data.get("entries", {}).pop(entry.entry_id, None)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload an entry after options change."""
    await hass.config_entries.async_reload(entry.entry_id)
