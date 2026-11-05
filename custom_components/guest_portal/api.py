"""Guest-facing HTTP API. Every entity operation is authorized server-side."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from pathlib import Path

from aiohttp import web
from homeassistant.components import persistent_notification
from homeassistant.components.http import HomeAssistantView

from .const import (
    CONF_AUTH_MODE,
    CONF_NOTIFY_SERVICE,
    CONF_SESSION_MINUTES,
    DOMAIN,
)


def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


def _active_entry_data(hass):
    """Return the active entry data, if the integration is configured."""
    domain_data = hass.data.get(DOMAIN, {})
    entry_id = domain_data.get("active_entry")
    return domain_data.get("entries", {}).get(entry_id)


def _notify(hass, service_name: str, title: str, message: str) -> None:
    """Send a notification through the configured HA notify service."""
    if not service_name or "." not in service_name:
        persistent_notification.async_create(hass, message, title=title)
        return
    domain, service = service_name.split(".", 1)
    hass.async_create_task(
        hass.services.async_call(
            domain, service, {"title": title, "message": message}, blocking=False
        )
    )


def _new_session(hass, data: dict, guest_id: str) -> str:
    token = secrets.token_urlsafe(36)
    minutes = int(data["entry"].options.get(
        CONF_SESSION_MINUTES,
        data["entry"].data.get(CONF_SESSION_MINUTES, 480),
    ))
    data["sessions"][token] = {
        "guest_id": guest_id,
        "expires": time.time() + minutes * 60,
    }
    return token


def _get_session(request: web.Request, data: dict):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    session = data["sessions"].get(token)
    if not session:
        return None
    if session["expires"] <= time.time():
        data["sessions"].pop(token, None)
        return None
    guest = data["storage"].data["guests"].get(session["guest_id"])
    if not guest or not guest.get("enabled", True):
        data["sessions"].pop(token, None)
        return None
    return token, session, guest


def _active_entity_lists(guest: dict, alone_mode: bool, data: dict | None = None) -> tuple[set[str], set[str]]:
    """Compatibility wrapper around the central policy manager."""
    manager = data.get("access_manager") if data else None
    if manager:
        return manager.entity_permissions(guest, alone_mode)
    readable = set(guest.get("read_entities", []))
    writable = set(guest.get("write_entities", []))
    if alone_mode:
        readable.update(guest.get("alone_entities", []))
        writable.update(guest.get("alone_write_entities", []))
    return readable, writable


class GuestLoginView(HomeAssistantView):
    """Password + optional OTP or administrator approval."""

    url = "/api/guest_portal/login"
    name = "api:guest_portal:login"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        data = _active_entry_data(request.app["hass"])
        if data is None:
            return _json_error("Guest Portal is not configured.", 503)
        if not _rate_allowed(data, request.remote or "unknown"):
            return _json_error("Too many attempts. Try again later.", 429)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return _json_error("Invalid JSON.")
        challenge_id = str(body.get("challenge_id", ""))
        otp = str(body.get("otp", ""))
        if challenge_id and otp:
            challenge = data["challenges"].get(challenge_id)
            if not challenge or challenge["expires"] <= time.time():
                data["challenges"].pop(challenge_id, None)
                return _json_error("Code expired or invalid.", 401)
            otp_hash = hashlib.sha256(otp.encode()).hexdigest()
            if not hmac.compare_digest(otp_hash, challenge["otp_hash"]):
                return _json_error("Code expired or invalid.", 401)
            data["challenges"].pop(challenge_id, None)
            token = _new_session(request.app["hass"], data, challenge["guest_id"])
            return web.json_response({"status": "ok", "token": token})

        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        if not username or len(username) > 64 or len(password) > 256:
            return _json_error("Invalid username or password.", 401)
        guest = next(
            (g for g in data["storage"].data["guests"].values()
             if g.get("username", "").casefold() == username.casefold()),
            None,
        )
        if not guest or not guest.get("enabled", True):
            return _json_error("Invalid username or password.", 401)
        if not await data["storage"].async_verify_password(
            password, guest["salt"], guest["password_hash"]
        ):
            return _json_error("Invalid username or password.", 401)

        mode = data["entry"].options.get(
            CONF_AUTH_MODE, data["entry"].data.get(CONF_AUTH_MODE, "approval")
        )
        if mode == "otp":
            code = f"{secrets.randbelow(1_000_000):06d}"
            challenge = secrets.token_urlsafe(24)
            data["challenges"][challenge] = {
                "guest_id": guest["guest_id"],
                "otp_hash": hashlib.sha256(code.encode()).hexdigest(),
                "expires": time.time() + 300,
            }
            service = data["entry"].options.get(
                CONF_NOTIFY_SERVICE,
                data["entry"].data.get(CONF_NOTIFY_SERVICE, ""),
            )
            _notify(
                request.app["hass"], service, "HA Guest Portal – Einmalcode",
                f"Einmalcode für Gast {guest['username']}: {code}. "
                "Der Code ist 5 Minuten gültig.",
            )
            return web.json_response(
                {"status": "otp_required", "challenge_id": challenge}, status=202
            )

        request_id = secrets.token_urlsafe(32)
        data["pending"][request_id] = {
            "guest_id": guest["guest_id"],
            "status": "pending",
            "expires": time.time() + 600,
        }
        service = data["entry"].options.get(
            CONF_NOTIFY_SERVICE, data["entry"].data.get(CONF_NOTIFY_SERVICE, "")
        )
        _notify(
            request.app["hass"], service, "HA Guest Portal – Freigabe erforderlich",
            f"Anmeldeversuch von {guest['username']}. "
            f"Freigabe über den Home-Assistant-Dienst "
            f"guest_portal.approve_request mit request_id: {request_id}. "
            "Die Anfrage läuft nach 10 Minuten ab.",
        )
        return web.json_response(
            {"status": "approval_required", "request_id": request_id}, status=202
        )


def _rate_allowed(data: dict, ip: str) -> bool:
    now = time.time()
    attempts = [stamp for stamp in data["attempts"].get(ip, []) if now - stamp < 300]
    if len(attempts) >= 8:
        data["attempts"][ip] = attempts
        return False
    attempts.append(now)
    data["attempts"][ip] = attempts
    return True


class GuestApprovalView(HomeAssistantView):
    """Poll an administrator approval request."""

    url = "/api/guest_portal/approval/{request_id}"
    name = "api:guest_portal:approval"
    requires_auth = False

    async def get(self, request: web.Request, request_id: str) -> web.Response:
        data = _active_entry_data(request.app["hass"])
        if data is None:
            return _json_error("Guest Portal is not configured.", 503)
        pending = data["pending"].get(request_id)
        if not pending or pending["expires"] <= time.time():
            expired = data["pending"].pop(request_id, None)
            if expired and expired.get("session_token"):
                data["sessions"].pop(expired["session_token"], None)
            return _json_error("Request expired.", 404)
        if pending["status"] == "pending":
            return web.json_response({"status": "pending"})
        if pending["status"] == "rejected":
            data["pending"].pop(request_id, None)
            return web.json_response({"status": "rejected"})
        token = pending.pop("session_token")
        data["pending"].pop(request_id, None)
        return web.json_response({"status": "approved", "token": token})


class GuestLogoutView(HomeAssistantView):
    """Revoke the current guest session."""

    url = "/api/guest_portal/logout"
    name = "api:guest_portal:logout"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        data = _active_entry_data(request.app["hass"])
        if data is None:
            return _json_error("Guest Portal is not configured.", 503)
        session = _get_session(request, data)
        if session:
            data["sessions"].pop(session[0], None)
        return web.json_response({"status": "ok"})


class GuestStatesView(HomeAssistantView):
    """Return only explicitly permitted entity states."""

    url = "/api/guest_portal/states"
    name = "api:guest_portal:states"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        data = _active_entry_data(request.app["hass"])
        if data is None:
            return _json_error("Guest Portal is not configured.", 503)
        session = _get_session(request, data)
        if not session:
            return _json_error("Authentication required.", 401)
        _, _, guest = session
        alone = data["alone_mode"]
        readable, writable = _active_entity_lists(guest, alone, data)
        from homeassistant.helpers import area_registry, device_registry, entity_registry

        hass = request.app["hass"]
        areas = area_registry.async_get(hass)
        devices = device_registry.async_get(hass)
        registry = entity_registry.async_get(hass)
        states = []
        manager = data.get("access_manager")
        for entity_id in sorted(readable):
            if manager and not manager.authorize_entity(
                guest, entity_id, "read", alone
            ):
                continue
            state = hass.states.get(entity_id)
            if state is None:
                continue
            entity_entry = registry.async_get(entity_id)
            area_id = entity_entry.area_id if entity_entry else None
            if not area_id and entity_entry and entity_entry.device_id:
                device = devices.async_get(entity_entry.device_id)
                area_id = device.area_id if device else None
            area = areas.async_get_area(area_id) if area_id else None
            states.append({
                "entity_id": entity_id,
                "state": state.state,
                "name": state.attributes.get("friendly_name", entity_id),
                "unit": state.attributes.get("unit_of_measurement"),
                "can_control": entity_id in writable,
                "area_id": area_id,
                "area_name": area.name if area else "Nicht zugewiesen",
                "domain": entity_id.split(".", 1)[0],
                "device_class": state.attributes.get("device_class"),
                "icon": state.attributes.get("icon"),
            })
        return web.json_response({"alone_mode": alone, "entities": states})


class GuestControlView(HomeAssistantView):
    """Allow a small, explicit set of actions on write-allowlisted entities."""

    url = "/api/guest_portal/control"
    name = "api:guest_portal:control"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        data = _active_entry_data(request.app["hass"])
        if data is None:
            return _json_error("Guest Portal is not configured.", 503)
        session = _get_session(request, data)
        if not session:
            return _json_error("Authentication required.", 401)
        _, _, guest = session
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return _json_error("Invalid JSON.")
        entity_id = str(body.get("entity_id", ""))
        service = str(body.get("service", ""))
        manager = data.get("access_manager")
        permitted = (
            manager.authorize_entity(guest, entity_id, "control", data["alone_mode"])
            if manager else entity_id in _active_entity_lists(guest, data["alone_mode"])[1]
        )
        if not permitted:
            return _json_error("This entity is not permitted.", 403)
        domain = entity_id.split(".", 1)[0]
        allowed_domains = {"light", "switch", "fan", "homeassistant"}
        if domain not in allowed_domains or service not in {"turn_on", "turn_off", "toggle"}:
            return _json_error("This action is not permitted.", 403)
        try:
            await request.app["hass"].services.async_call(
                domain, service, {"entity_id": entity_id}, blocking=True
            )
        except Exception:  # noqa: BLE001
            return _json_error("Home Assistant could not perform this action.", 400)
        return web.json_response({"status": "ok"})


class GuestPortalPageView(HomeAssistantView):
    """Serve the small guest portal web page."""

    url = "/guest-portal"
    name = "guest_portal:page"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        page = Path(__file__).parent / "www" / "index.html"
        hass = request.app["hass"]
        content = await hass.async_add_executor_job(lambda: page.read_text(encoding="utf-8"))
        return web.Response(text=content, content_type="text/html")


class GuestAdminApiView(HomeAssistantView):
    """Administrator-only API for guest and approval management."""

    url = "/api/guest_portal/admin"
    name = "api:guest_portal:admin"
    requires_auth = True

    @staticmethod
    def _is_admin(request: web.Request) -> bool:
        user = request.get("hass_user")
        return bool(user and user.is_admin)

    async def get(self, request: web.Request) -> web.Response:
        if not self._is_admin(request):
            return _json_error("Administrator access required.", 403)
        data = _active_entry_data(request.app["hass"])
        if data is None:
            return _json_error("Guest Portal is not configured.", 503)
        guests = [
            {
                "guest_id": guest["guest_id"],
                "username": guest["username"],
                "enabled": guest.get("enabled", True),
                "read_entities": guest.get("read_entities", []),
                "write_entities": guest.get("write_entities", []),
                "alone_entities": guest.get("alone_entities", []),
                "alone_write_entities": guest.get("alone_write_entities", []),
            }
            for guest in data["storage"].data["guests"].values()
        ]
        now = time.time()
        pending = [
            {
                "request_id": request_id,
                "username": data["storage"].data["guests"].get(item["guest_id"], {}).get("username", "unknown"),
                "expires": int(item["expires"]),
            }
            for request_id, item in data["pending"].items()
            if item["status"] == "pending" and item["expires"] > now
        ]
        return web.json_response({
            "guests": guests,
            "pending": pending,
            "entities": [
                {
                    "entity_id": state.entity_id,
                    "name": state.attributes.get("friendly_name", state.entity_id),
                    "state": state.state,
                    "unit": state.attributes.get("unit_of_measurement"),
                }
                for state in sorted(
                    request.app["hass"].states.async_all(),
                    key=lambda item: item.entity_id,
                )
            ],
            "alone_mode": data["alone_mode"],
        })

    async def post(self, request: web.Request) -> web.Response:
        if not self._is_admin(request):
            return _json_error("Administrator access required.", 403)
        data = _active_entry_data(request.app["hass"])
        if data is None:
            return _json_error("Guest Portal is not configured.", 503)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return _json_error("Invalid JSON.")
        action = body.get("action")
        if action == "add_guest":
            username = str(body.get("username", "")).strip()
            guest_id = str(body.get("guest_id") or username).strip()
            password = str(body.get("password", ""))
            if not username or len(username) > 64 or len(password) < 12 or len(password) > 256:
                return _json_error("Username is required and password must contain 12–256 characters.")
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", guest_id):
                return _json_error("Guest ID may contain only letters, numbers, _ and -.")
            guests = data["storage"].data["guests"]
            if guest_id in guests or any(g["username"].casefold() == username.casefold() for g in guests.values()):
                return _json_error("Guest ID or username already exists.", 409)
            salt, digest = await data["storage"].async_hash_password(password)
            data["storage"].data["guests"][guest_id] = {
                "guest_id": guest_id,
                "username": username,
                "salt": salt,
                "password_hash": digest,
                "read_entities": _clean_entity_list(body.get("read_entities")),
                "write_entities": _clean_entity_list(body.get("write_entities")),
                "alone_entities": _clean_entity_list(body.get("alone_entities")),
                "alone_write_entities": _clean_entity_list(body.get("alone_write_entities")),
                "enabled": True,
            }
            await data["storage"].async_save()
            return web.json_response({"status": "created"})
        if action == "update_guest":
            guest_id = str(body.get("guest_id", ""))
            guest = data["storage"].data["guests"].get(guest_id)
            if not guest:
                return _json_error("Guest not found.", 404)
            username = str(body.get("username", guest["username"])).strip()
            if not username or len(username) > 64:
                return _json_error("Username must contain 1–64 characters.")
            if any(other_id != guest_id and item["username"].casefold() == username.casefold()
                   for other_id, item in data["storage"].data["guests"].items()):
                return _json_error("Username already exists.", 409)
            guest["username"] = username
            for field in ("read_entities", "write_entities", "alone_entities", "alone_write_entities"):
                guest[field] = _clean_entity_list(body.get(field, guest.get(field, [])))
            password = str(body.get("password", ""))
            if password:
                if len(password) < 12 or len(password) > 256:
                    return _json_error("New password must contain 12–256 characters.")
                salt, digest = await data["storage"].async_hash_password(password)
                guest["salt"], guest["password_hash"] = salt, digest
                for token, session in list(data["sessions"].items()):
                    if session["guest_id"] == guest_id:
                        data["sessions"].pop(token, None)
            await data["storage"].async_save()
            return web.json_response({"status": "updated"})
        if action in {"remove_guest", "set_guest_enabled"}:
            guest_id = str(body.get("guest_id", ""))
            guest = data["storage"].data["guests"].get(guest_id)
            if not guest:
                return _json_error("Guest not found.", 404)
            if action == "remove_guest":
                data["storage"].data["guests"].pop(guest_id, None)
                enabled = False
            else:
                enabled = bool(body.get("enabled"))
                guest["enabled"] = enabled
            if not enabled:
                for token, session in list(data["sessions"].items()):
                    if session["guest_id"] == guest_id:
                        data["sessions"].pop(token, None)
            await data["storage"].async_save()
            return web.json_response({"status": "ok"})
        if action == "set_alone_mode":
            enabled = bool(body.get("enabled"))
            data["alone_mode"] = enabled
            request.app["hass"].bus.async_fire("guest_portal_alone_mode_changed", {
                "entry_id": data["entry"].entry_id, "enabled": enabled, "source": "admin_dashboard"
            })
            return web.json_response({"status": "ok", "alone_mode": enabled})
        if action == "approve_request":
            request_id = str(body.get("request_id", ""))
            pending = data["pending"].get(request_id)
            if not pending or pending["expires"] <= time.time():
                return _json_error("Approval request expired.", 404)
            if body.get("approved") is True:
                pending["status"] = "approved"
                pending["session_token"] = _new_session(request.app["hass"], data, pending["guest_id"])
            else:
                pending["status"] = "rejected"
            return web.json_response({"status": pending["status"]})
        return _json_error("Unknown admin action.")


def _clean_entity_list(value) -> list[str]:
    """Accept only syntactically valid entity IDs from admin input."""
    if not isinstance(value, list):
        return []
    result = []
    for entity_id in value:
        if isinstance(entity_id, str) and "." in entity_id and len(entity_id) <= 255:
            domain, object_id = entity_id.split(".", 1)
            if domain.replace("_", "").isalnum() and object_id.replace("_", "").replace("-", "").isalnum():
                result.append(entity_id)
    return sorted(set(result))


class GuestAdminPageView(HomeAssistantView):
    """Serve the administrator dashboard."""

    url = "/guest-portal/admin"
    name = "guest_portal:admin_page"
    # The page shell is public; its data API requires an authenticated admin token.
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        page = Path(__file__).parent / "www" / "admin.html"
        hass = request.app["hass"]
        content = await hass.async_add_executor_job(
            lambda: page.read_text(encoding="utf-8")
        )
        return web.Response(text=content, content_type="text/html")
