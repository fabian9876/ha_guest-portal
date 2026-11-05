"""HA Guest Portal integration entry point.

Version 0.1.0 provides configuration and a manual alone-mode service.
Guest authentication and entity proxying are intentionally not implemented yet.
"""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    ATTR_ENABLED,
    DOMAIN,
    EVENT_ALONE_MODE_CHANGED,
    SERVICE_SET_ALONE_MODE,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = []


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration domain and its domain-level service."""
    domain_data = hass.data.setdefault(DOMAIN, {"entries": {}})

    async def async_set_alone_mode(call: ServiceCall) -> None:
        """Manually enable or disable alone mode for the active entry."""
        entries = domain_data["entries"]
        if not entries:
            _LOGGER.warning("Cannot change alone mode: no config entry is loaded")
            return

        enabled = call.data[ATTR_ENABLED]
        for entry_id, entry_data in entries.items():
            entry_data["alone_mode"] = enabled
            hass.bus.async_fire(
                EVENT_ALONE_MODE_CHANGED,
                {"entry_id": entry_id, "enabled": enabled, "source": "service"},
            )
        _LOGGER.info("Alone mode %s", "enabled" if enabled else "disabled")

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ALONE_MODE,
        async_set_alone_mode,
        schema=vol.Schema({vol.Required(ATTR_ENABLED): bool}),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a configured entry."""
    domain_data = hass.data.setdefault(DOMAIN, {"entries": {}})
    domain_data["entries"][entry.entry_id] = {"alone_mode": False}
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
