"""Register the guest and administrator sidebar panels."""

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PANEL_STATIC_URL = f"/{DOMAIN}_panel"


async def async_register_panels(hass: HomeAssistant) -> None:
    """Register both sidebar panels and their shared web component."""
    panel_dir = Path(__file__).parent / "www" / "panel"
    static_key = f"{DOMAIN}_panel_static_registered"
    if not hass.data.get(static_key):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_STATIC_URL, str(panel_dir), False)]
        )
        hass.data[static_key] = True
    module_url = f"{PANEL_STATIC_URL}/guest-portal-panel.js"

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="ha-guest-portal-panel",
        frontend_url_path="guest-portal",
        sidebar_title="Gäste",
        sidebar_icon="mdi:home-account",
        module_url=module_url,
        config={"path": "/guest-portal"},
        require_admin=False,
    )
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="ha-guest-portal-panel",
        frontend_url_path="guest-portal-admin",
        sidebar_title="Gastverwaltung",
        sidebar_icon="mdi:account-cog",
        module_url=module_url,
        config={"path": "/guest-portal/admin"},
        require_admin=True,
    )
