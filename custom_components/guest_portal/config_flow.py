"""Config flow for HA Guest Portal."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ABSENCE_DELAY,
    CONF_NOTIFY_SERVICE,
    CONF_PRESENCE_ENTITIES,
    CONF_PRESENCE_ZONE,
    CONF_SESSION_MINUTES,
    DEFAULT_ABSENCE_DELAY,
    DEFAULT_SESSION_MINUTES,
    DOMAIN,
)


class GuestPortalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HA Guest Portal."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Configure presence and notification settings."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title="HA Guest Portal", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_PRESENCE_ZONE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="zone")
                ),
                vol.Required(CONF_PRESENCE_ENTITIES, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["person", "device_tracker"], multiple=True
                    )
                ),
                vol.Required(
                    CONF_ABSENCE_DELAY, default=DEFAULT_ABSENCE_DELAY
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=180, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(CONF_NOTIFY_SERVICE, default=""): str,
                vol.Required(
                    CONF_SESSION_MINUTES, default=DEFAULT_SESSION_MINUTES
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=10080, step=5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GuestPortalOptionsFlow()


class GuestPortalOptionsFlow(config_entries.OptionsFlow):
    """Handle options for an existing config entry."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        entry = self.config_entry
        current = {**entry.data, **entry.options}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PRESENCE_ZONE, default=current.get(CONF_PRESENCE_ZONE)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="zone")
                ),
                vol.Required(
                    CONF_PRESENCE_ENTITIES,
                    default=current.get(CONF_PRESENCE_ENTITIES, []),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["person", "device_tracker"], multiple=True
                    )
                ),
                vol.Required(
                    CONF_ABSENCE_DELAY,
                    default=current.get(CONF_ABSENCE_DELAY, DEFAULT_ABSENCE_DELAY),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=180, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_NOTIFY_SERVICE,
                    default=current.get(CONF_NOTIFY_SERVICE, ""),
                ): str,
                vol.Required(
                    CONF_SESSION_MINUTES,
                    default=current.get(
                        CONF_SESSION_MINUTES, DEFAULT_SESSION_MINUTES
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=10080, step=5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
