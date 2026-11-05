"""Persistent guest storage and password hashing."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_ITERATIONS = 310_000


class GuestStorage:
    """Persist guest accounts without storing plaintext passwords."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, 1, f"{DOMAIN}_guests")
        self.data: dict = {"guests": {}}

    async def async_load(self) -> None:
        """Load persisted guest records."""
        stored = await self._store.async_load()
        if isinstance(stored, dict) and isinstance(stored.get("guests"), dict):
            self.data = stored

    async def async_save(self) -> None:
        """Persist guest records."""
        await self._store.async_save(self.data)

    @staticmethod
    async def async_hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
        """Hash a password off the event loop using PBKDF2-HMAC-SHA256."""
        import asyncio

        salt = salt or secrets.token_bytes(16)
        digest = await asyncio.to_thread(
            hashlib.pbkdf2_hmac, "sha256", password.encode(), salt, _ITERATIONS
        )
        return salt.hex(), digest.hex()

    @staticmethod
    async def async_verify_password(password: str, salt_hex: str, digest_hex: str) -> bool:
        """Constant-time password verification."""
        import asyncio

        try:
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(digest_hex)
        except ValueError:
            return False
        actual = await asyncio.to_thread(
            hashlib.pbkdf2_hmac, "sha256", password.encode(), salt, _ITERATIONS
        )
        return hmac.compare_digest(actual, expected)
