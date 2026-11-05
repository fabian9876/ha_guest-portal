"""Central policy, session lifecycle and audit service for guest access."""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
EVENT_ACCESS_DECISION = "guest_portal_access_decision"
EVENT_SESSION_REVOKED = "guest_portal_session_revoked"
AUDIT_LIMIT = 500


class GuestAccessManager:
    """Single policy decision point for all integration-managed guest routes."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    @staticmethod
    def entity_permissions(
        guest: dict[str, Any], alone_mode: bool
    ) -> tuple[set[str], set[str]]:
        readable = set(guest.get("read_entities", []))
        writable = set(guest.get("write_entities", []))
        if alone_mode:
            readable.update(guest.get("alone_entities", []))
            writable.update(guest.get("alone_write_entities", []))
        return readable, writable

    @staticmethod
    def guest_is_active(guest: dict[str, Any], now: float | None = None) -> bool:
        now = time.time() if now is None else now
        expires_at = guest.get("expires_at")
        return bool(guest.get("enabled", True)) and (
            not expires_at or float(expires_at) > now
        )

    @staticmethod
    def session_is_active(session: dict[str, Any], guest: dict[str, Any]) -> bool:
        now = time.time()
        return (
            session.get("expires", 0) > now
            and GuestAccessManager.guest_is_active(guest, now)
            and session.get("guest_id") == guest.get("guest_id")
        )

    @staticmethod
    def append_audit(data: dict[str, Any], record: dict[str, Any]) -> None:
        audit = data.setdefault("audit", [])
        audit.append({"timestamp": int(time.time()), **record})
        del audit[:-AUDIT_LIMIT]

    def authorize_entity(
        self, guest: dict[str, Any], entity_id: str, operation: str,
        alone_mode: bool, data: dict[str, Any] | None = None,
    ) -> bool:
        readable, writable = self.entity_permissions(guest, alone_mode)
        allowed = self.guest_is_active(guest) and (
            entity_id in readable if operation == "read"
            else entity_id in writable if operation == "control"
            else False
        )
        record = {
            "guest_id": guest.get("guest_id", "unknown"),
            "username": guest.get("username", "unknown"),
            "entity_id": entity_id,
            "operation": operation,
            "allowed": allowed,
            "alone_mode": bool(alone_mode),
        }
        if data is not None:
            self.append_audit(data, record)
        self.hass.bus.async_fire(EVENT_ACCESS_DECISION, record)
        if not allowed:
            _LOGGER.warning(
                "Denied guest %s %s access to %s",
                guest.get("guest_id", "unknown"), operation, entity_id,
            )
        return allowed

    def revoke_guest_sessions(self, data: dict[str, Any], guest_id: str) -> int:
        revoked = 0
        for token, session in list(data.setdefault("sessions", {}).items()):
            if session.get("guest_id") == guest_id:
                data["sessions"].pop(token, None)
                revoked += 1
        self.append_audit(data, {
            "guest_id": guest_id, "operation": "revoke_sessions",
            "allowed": True, "count": revoked,
        })
        self.hass.bus.async_fire(EVENT_SESSION_REVOKED, {
            "guest_id": guest_id, "count": revoked,
        })
        return revoked

    def revoke_all_sessions(self, data: dict[str, Any]) -> int:
        count = len(data.setdefault("sessions", {}))
        data["sessions"].clear()
        self.append_audit(data, {
            "guest_id": "*", "operation": "revoke_all_sessions",
            "allowed": True, "count": count,
        })
        self.hass.bus.async_fire(EVENT_SESSION_REVOKED, {
            "guest_id": "*", "count": count,
        })
        return count

    @staticmethod
    def public_sessions(data: dict[str, Any]) -> list[dict[str, Any]]:
        now = time.time()
        guests = data["storage"].data["guests"]
        result = []
        for token, session in list(data.setdefault("sessions", {}).items()):
            guest = guests.get(session.get("guest_id"))
            if not guest or not GuestAccessManager.session_is_active(session, guest):
                data["sessions"].pop(token, None)
                continue
            result.append({
                "session_id": secrets.token_hex(6) if False else __import__("hashlib").sha256(token.encode()).hexdigest()[:12],
                "guest_id": session["guest_id"],
                "username": guest.get("username", "unknown"),
                "created": int(session.get("created", now)),
                "expires": int(session["expires"]),
            })
        return result
