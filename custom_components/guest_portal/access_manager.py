"""Central policy engine for every integration-managed guest operation."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
EVENT_ACCESS_DECISION = "guest_portal_access_decision"


class GuestAccessManager:
    """Single policy decision point for guest-facing integration endpoints.

    This manager governs only requests routed through this integration. It does
    not replace Home Assistant authentication or restrict native HA users.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    @staticmethod
    def entity_permissions(
        guest: dict[str, Any], alone_mode: bool
    ) -> tuple[set[str], set[str]]:
        """Return the effective read and control allowlists for a guest."""
        readable = set(guest.get("read_entities", []))
        writable = set(guest.get("write_entities", []))
        if alone_mode:
            readable.update(guest.get("alone_entities", []))
            writable.update(guest.get("alone_write_entities", []))
        return readable, writable

    def authorize_entity(
        self,
        guest: dict[str, Any],
        entity_id: str,
        operation: str,
        alone_mode: bool,
    ) -> bool:
        """Make one authoritative allowlist decision and emit an audit event."""
        readable, writable = self.entity_permissions(guest, alone_mode)
        allowed = bool(guest.get("enabled", True)) and (
            entity_id in readable if operation == "read"
            else entity_id in writable if operation == "control"
            else False
        )
        self.hass.bus.async_fire(EVENT_ACCESS_DECISION, {
            "guest_id": guest.get("guest_id", "unknown"),
            "entity_id": entity_id,
            "operation": operation,
            "allowed": allowed,
            "alone_mode": bool(alone_mode),
        })
        if not allowed:
            _LOGGER.warning(
                "Denied guest %s %s access to %s",
                guest.get("guest_id", "unknown"), operation, entity_id,
            )
        return allowed
