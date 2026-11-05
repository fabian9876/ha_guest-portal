"""HA Guest Portal integration setup and administrator services."""

from __future__ import annotations

import asyncio
import logging
import re

import voluptuous as vol
from homeassistant.components import frontend
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import selector
from homeassistant.helpers.event import async_track_state_change_event

from .api import (
    GuestAdminApiView,
    GuestAdminPageView,
    GuestApprovalView,
    GuestControlView,
    GuestLoginView,
    GuestLogoutView,
    GuestPortalPageView,
    GuestStatesView,
    _new_session,
)
from .const import (
    ATTR_ENABLED,
    CONF_ABSENCE_DELAY,
    CONF_AUTO_ALONE_MODE,
    CONF_PRESENCE_ENTITIES,
    CONF_PRESENCE_ZONE,
    DOMAIN,
    EVENT_ALONE_MODE_CHANGED,
    EVENT_GUEST_REQUEST,
    SERVICE_ADD_GUEST,
    SERVICE_APPROVE_REQUEST,
    SERVICE_REMOVE_GUEST,
    SERVICE_REVOKE_ALL_SESSIONS,
    SERVICE_REVOKE_GUEST_SESSIONS,
    SERVICE_SET_ALONE_MODE,
    SERVICE_SET_GUEST_ENABLED,
)
from .access_manager import GuestAccessManager
from .panel import async_register_panels
from .storage import GuestStorage

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = []
ENTITY_LIST = selector.EntitySelector(
    selector.EntitySelectorConfig(multiple=True)
)
SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


async def _require_admin(hass: HomeAssistant, call: ServiceCall) -> bool:
    """Only authenticated Home Assistant administrators may manage guests."""
    user_id = call.context.user_id
    if not user_id:
        return False
    user = await hass.auth.async_get_user(user_id)
    return bool(user and user.is_admin)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register views and service handlers."""
    hass.data.setdefault(DOMAIN, {"entries": {}, "active_entry": None})
    for view in (
        GuestPortalPageView,
        GuestAdminPageView,
        GuestAdminApiView,
        GuestLoginView,
        GuestApprovalView,
        GuestLogoutView,
        GuestStatesView,
        GuestControlView,
    ):
        hass.http.register_view(view())

    async def set_alone_mode(call: ServiceCall) -> None:
        if not await _require_admin(hass, call):
            _LOGGER.warning("Rejected non-admin attempt to change alone mode")
            return
        for entry_id, data in hass.data[DOMAIN]["entries"].items():
            data["alone_mode"] = call.data[ATTR_ENABLED]
            hass.bus.async_fire(
                EVENT_ALONE_MODE_CHANGED,
                {"entry_id": entry_id, "enabled": call.data[ATTR_ENABLED], "source": "manual"},
            )

    async def add_guest(call: ServiceCall) -> None:
        if not await _require_admin(hass, call):
            _LOGGER.warning("Rejected non-admin guest creation")
            return
        entry_data = _active_data(hass)
        if entry_data is None:
            return
        username = call.data["username"].strip()
        guest_id = call.data.get("guest_id", username).strip()
        password = call.data["password"]
        if not SLUG_RE.fullmatch(guest_id) or not username or len(password) < 12:
            _LOGGER.error("Guest not created: ID must be simple and password at least 12 characters")
            return
        guests = entry_data["storage"].data["guests"]
        if guest_id in guests or any(
            g.get("username", "").casefold() == username.casefold()
            for g in guests.values()
        ):
            _LOGGER.error("Guest not created: ID or username already exists")
            return
        salt, digest = await entry_data["storage"].async_hash_password(password)
        guests[guest_id] = {
            "guest_id": guest_id,
            "username": username,
            "salt": salt,
            "password_hash": digest,
            "read_entities": list(call.data.get("read_entities", [])),
            "write_entities": list(call.data.get("write_entities", [])),
            "alone_entities": list(call.data.get("alone_entities", [])),
            "alone_write_entities": list(call.data.get("alone_write_entities", [])),
            "enabled": True,
        }
        await entry_data["storage"].async_save()
        _LOGGER.info("Created guest account %s", guest_id)

    async def remove_guest(call: ServiceCall) -> None:
        if not await _require_admin(hass, call):
            return
        data = _active_data(hass)
        if data is None:
            return
        guest_id = call.data["guest_id"]
        data["storage"].data["guests"].pop(guest_id, None)
        for token, session in list(data["sessions"].items()):
            if session["guest_id"] == guest_id:
                data["sessions"].pop(token, None)
        await data["storage"].async_save()

    async def set_guest_enabled(call: ServiceCall) -> None:
        if not await _require_admin(hass, call):
            return
        data = _active_data(hass)
        if data is None:
            return
        guest = data["storage"].data["guests"].get(call.data["guest_id"])
        if not guest:
            return
        guest["enabled"] = call.data["enabled"]
        if not guest["enabled"]:
            for token, session in list(data["sessions"].items()):
                if session["guest_id"] == call.data["guest_id"]:
                    data["sessions"].pop(token, None)
        await data["storage"].async_save()

    async def revoke_guest_sessions(call: ServiceCall) -> None:
        if not await _require_admin(hass, call):
            return
        data = _active_data(hass)
        if data is None:
            return
        count = data["access_manager"].revoke_guest_sessions(data, call.data["guest_id"])
        _LOGGER.info("Revoked %s sessions for guest %s", count, call.data["guest_id"])

    async def revoke_all_sessions(call: ServiceCall) -> None:
        if not await _require_admin(hass, call):
            return
        data = _active_data(hass)
        if data is None:
            return
        count = data["access_manager"].revoke_all_sessions(data)
        _LOGGER.warning("Administrator revoked all %s guest sessions", count)

    async def approve_request(call: ServiceCall) -> None:
        if not await _require_admin(hass, call):
            _LOGGER.warning("Rejected non-admin approval attempt")
            return
        data = _active_data(hass)
        if data is None:
            return
        pending = data["pending"].get(call.data["request_id"])
        if not pending or pending["expires"] <= __import__("time").time():
            return
        if call.data["approved"]:
            pending["status"] = "approved"
            pending["session_token"] = _new_session(hass, data, pending["guest_id"])
        else:
            pending["status"] = "rejected"

    hass.services.async_register(
        DOMAIN, SERVICE_SET_ALONE_MODE, set_alone_mode,
        schema=vol.Schema({vol.Required(ATTR_ENABLED): bool}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_GUEST, add_guest,
        schema=vol.Schema({
            vol.Required("username"): vol.All(str, vol.Length(min=1, max=64)),
            vol.Required("password"): vol.All(str, vol.Length(min=12, max=256)),
            vol.Optional("guest_id"): str,
            vol.Optional("read_entities", default=[]): ENTITY_LIST,
            vol.Optional("write_entities", default=[]): ENTITY_LIST,
            vol.Optional("alone_entities", default=[]): ENTITY_LIST,
            vol.Optional("alone_write_entities", default=[]): ENTITY_LIST,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_GUEST, remove_guest,
        schema=vol.Schema({vol.Required("guest_id"): str}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_GUEST_ENABLED, set_guest_enabled,
        schema=vol.Schema({
            vol.Required("guest_id"): str, vol.Required("enabled"): bool
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REVOKE_GUEST_SESSIONS, revoke_guest_sessions,
        schema=vol.Schema({vol.Required("guest_id"): str}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REVOKE_ALL_SESSIONS, revoke_all_sessions,
        schema=vol.Schema({}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_APPROVE_REQUEST, approve_request,
        schema=vol.Schema({
            vol.Required("request_id"): str, vol.Required("approved"): bool
        }),
    )
    return True


def _active_data(hass: HomeAssistant):
    entry_id = hass.data.get(DOMAIN, {}).get("active_entry")
    return hass.data.get(DOMAIN, {}).get("entries", {}).get(entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load persisted guest data and start presence monitoring."""
    await async_register_panels(hass)

    domain_data = hass.data[DOMAIN]
    storage = GuestStorage(hass)
    await storage.async_load()
    data = {
        "entry": entry,
        "storage": storage,
        "access_manager": GuestAccessManager(hass),
        "audit": storage.data.setdefault("audit", []),
        "alone_mode": False,
        "sessions": {},
        "pending": {},
        "challenges": {},
        "attempts": {},
        "presence_task": None,
    }
    domain_data["entries"][entry.entry_id] = data
    domain_data["active_entry"] = entry.entry_id

    entities = entry.options.get(
        CONF_PRESENCE_ENTITIES, entry.data.get(CONF_PRESENCE_ENTITIES, [])
    )
    auto_mode = entry.options.get(
        CONF_AUTO_ALONE_MODE, entry.data.get(CONF_AUTO_ALONE_MODE, False)
    )

    async def update_presence() -> None:
        if not auto_mode:
            return
        zone_id = entry.options.get(
            CONF_PRESENCE_ZONE, entry.data.get(CONF_PRESENCE_ZONE, "zone.home")
        )
        zone_state = hass.states.get(zone_id)
        states = [hass.states.get(entity_id) for entity_id in entities]
        if (
            zone_state is None
            or zone_state.state in {"unknown", "unavailable"}
            or not states
            or any(state is None or state.state in {"unknown", "unavailable"} for state in states)
        ):
            data["alone_mode"] = False
            hass.bus.async_fire(EVENT_ALONE_MODE_CHANGED, {
                "entry_id": entry.entry_id, "enabled": False, "source": "presence_unknown"
            })
            return
        else:
            zone_name = zone_state.attributes.get("friendly_name", zone_id.split(".", 1)[-1])
            at_home = any(state.state in {"home", zone_name} for state in states)
            if at_home:
                data["alone_mode"] = False
                hass.bus.async_fire(EVENT_ALONE_MODE_CHANGED, {
                    "entry_id": entry.entry_id, "enabled": False, "source": "presence"
                })
                return
            desired = True
        delay = int(entry.options.get(
            CONF_ABSENCE_DELAY, entry.data.get(CONF_ABSENCE_DELAY, 5)
        ))
        if data["presence_task"]:
            data["presence_task"].cancel()
        async def delayed_update():
            await asyncio.sleep(delay * 60)
            current = [hass.states.get(entity_id) for entity_id in entities]
            if not current or any(s is None or s.state in {"unknown", "unavailable"} for s in current):
                data["alone_mode"] = False
            else:
                current_zone = hass.states.get(zone_id)
                current_name = current_zone.attributes.get("friendly_name", "home") if current_zone else "home"
                data["alone_mode"] = not any(s.state in {"home", current_name} for s in current)
            hass.bus.async_fire(EVENT_ALONE_MODE_CHANGED, {
                "entry_id": entry.entry_id, "enabled": data["alone_mode"], "source": "presence"
            })
        if desired:
            data["presence_task"] = hass.async_create_task(delayed_update())

    if auto_mode and entities:
        unsub = async_track_state_change_event(
            hass, entities, lambda event: hass.async_create_task(update_presence())
        )
        entry.async_on_unload(unsub)
        await update_presence()

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry and revoke all guest sessions."""
    data = hass.data[DOMAIN]["entries"].pop(entry.entry_id, None)
    if data and data["presence_task"]:
        data["presence_task"].cancel()
    hass.data[DOMAIN]["active_entry"] = next(iter(hass.data[DOMAIN]["entries"]), None)
    if not hass.data[DOMAIN]["entries"]:
        frontend.async_remove_panel(hass, "guest-portal")
        frontend.async_remove_panel(hass, "guest-portal-admin")
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry after options change."""
    await hass.config_entries.async_reload(entry.entry_id)
