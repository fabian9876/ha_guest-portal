"""Guest-facing HTTP API. Every entity operation is authorized server-side."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from pathlib import Path

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .const import (
    CONF_AUTH_MODE,
    CONF_NOTIFY_SERVICE,
    CONF_SESSION_MINUTES,
    DOMAIN,
)


def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


def _notify(hass, service_name: str, title: str, message: str) -> None:
    """Send a notification through the configured HA notify service."""
    if not service_name or "." not in service_name:
        hass.components.persistent_notification.async_create(message, title=title)
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


def _active_entity_lists(guest: dict, alone_mode: bool) -> tuple[set[str], set[str]]:
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
        data = self.hass.data[DOMAIN]["entries"][self.hass.data[DOMAIN]["active_entry"]]
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
            token = _new_session(self.hass, data, challenge["guest_id"])
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
                self.hass, service, "HA Guest Portal – Einmalcode",
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
            self.hass, service, "HA Guest Portal – Freigabe erforderlich",
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
        data = self.hass.data[DOMAIN]["entries"][self.hass.data[DOMAIN]["active_entry"]]
        pending = data["pending"].get(request_id)
        if not pending or pending["expires"] <= time.time():
            data["pending"].pop(request_id, None)
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
        data = self.hass.data[DOMAIN]["entries"][self.hass.data[DOMAIN]["active_entry"]]
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
        data = self.hass.data[DOMAIN]["entries"][self.hass.data[DOMAIN]["active_entry"]]
        session = _get_session(request, data)
        if not session:
            return _json_error("Authentication required.", 401)
        _, _, guest = session
        alone = data["alone_mode"]
        readable, writable = _active_entity_lists(guest, alone)
        states = []
        for entity_id in sorted(readable):
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            states.append({
                "entity_id": entity_id,
                "state": state.state,
                "name": state.attributes.get("friendly_name", entity_id),
                "unit": state.attributes.get("unit_of_measurement"),
                "can_control": entity_id in writable,
            })
        return web.json_response({"alone_mode": alone, "entities": states})


class GuestControlView(HomeAssistantView):
    """Allow a small, explicit set of actions on write-allowlisted entities."""

    url = "/api/guest_portal/control"
    name = "api:guest_portal:control"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        data = self.hass.data[DOMAIN]["entries"][self.hass.data[DOMAIN]["active_entry"]]
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
        _, writable = _active_entity_lists(guest, data["alone_mode"])
        if entity_id not in writable:
            return _json_error("This entity is not permitted.", 403)
        domain = entity_id.split(".", 1)[0]
        allowed_domains = {"light", "switch", "fan", "homeassistant"}
        if domain not in allowed_domains or service not in {"turn_on", "turn_off", "toggle"}:
            return _json_error("This action is not permitted.", 403)
        try:
            await self.hass.services.async_call(
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
        return web.Response(text=page.read_text(encoding="utf-8"), content_type="text/html")
