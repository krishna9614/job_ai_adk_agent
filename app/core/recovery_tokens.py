"""Sealed password-recovery values.

* Recovery tickets: the Supabase session created from a reset link never leaves the backend;
  callers only get an encrypted, 15-minute ticket that is accepted by POST /auth/password/reset
  and nowhere else (it is not a JWT, so it can never authenticate a normal API request).
* Recovery state: the PKCE code verifier for a reset email, sealed so the frontend can keep it in
  an HttpOnly cookie until the emailed link comes back with `?code=`.
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
# Hosted Supabase email links expire after 1 hour by default.
RECOVERY_STATE_TTL_SECONDS = 60 * 60

_TICKET = "ticket:"
_STATE = "pkce:"


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


def _seal(purpose: str, value: str) -> str:
    return _fernet().encrypt((purpose + value).encode()).decode()


def _open(purpose: str, sealed: str, ttl: int) -> str | None:
    try:
        value = _fernet().decrypt(sealed.encode(), ttl=ttl).decode()
    except (InvalidToken, ValueError):
        return None
    return value.removeprefix(purpose) if value.startswith(purpose) else None


def seal_recovery_token(access_token: str) -> str:
    return _seal(_TICKET, access_token)


def open_recovery_token(ticket: str) -> str | None:
    """The Supabase recovery access token, or None if the ticket is forged, malformed or expired."""
    return _open(_TICKET, ticket, RECOVERY_TTL_SECONDS)


def new_pkce_pair() -> tuple[str, str]:
    """A fresh (code_verifier, S256 code_challenge) pair for a password-reset email."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def seal_recovery_state(code_verifier: str) -> str:
    return _seal(_STATE, code_verifier)


def open_recovery_state(state: str) -> str | None:
    """The PKCE code verifier, or None if the state is forged, malformed or older than the link."""
    return _open(_STATE, state, RECOVERY_STATE_TTL_SECONDS)
