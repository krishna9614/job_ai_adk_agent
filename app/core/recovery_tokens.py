"""Sealed password-recovery tickets.

The Supabase session created from a reset link never leaves the backend: callers only get an
encrypted, 15-minute ticket that is accepted by POST /auth/password/reset and nowhere else
(it is not a JWT, so it can never authenticate a normal API request).
"""

import base64
import hashlib
import logging
import secrets
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

logger = logging.getLogger(__name__)

RECOVERY_TTL_SECONDS = 15 * 60


@lru_cache
def _fernet() -> Fernet:
    secret = get_settings().recovery_token_secret
    if not secret:
        logger.warning(
            "RECOVERY_TOKEN_SECRET is not set: using a per-process key, so reset sessions end "
            "on restart and are not shared between workers"
        )
        secret = secrets.token_urlsafe(32)
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def seal_recovery_token(access_token: str) -> str:
    return _fernet().encrypt(access_token.encode()).decode()


def open_recovery_token(ticket: str) -> str | None:
    """The Supabase recovery access token, or None if the ticket is forged, malformed or expired."""
    try:
        return _fernet().decrypt(ticket.encode(), ttl=RECOVERY_TTL_SECONDS).decode()
    except (InvalidToken, ValueError):
        return None
