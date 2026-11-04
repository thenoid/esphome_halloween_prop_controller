"""Expiring browser credentials, signed with the configured API token."""
import hashlib
import hmac
import re
import secrets
import time

COOKIE_NAME = "controller_events_session"
COOKIE_PATH = "/api/v1"
SESSION_SECONDS = 7 * 24 * 60 * 60
_FORMAT = re.compile(r"v1\.([0-9]{1,12})\.([A-Za-z0-9_-]{43})\.([a-f0-9]{64})")


def _signature(payload: str, api_token: str) -> str:
    return hmac.new(api_token.encode(), b"controller-events-browser-session\0" + payload.encode(), hashlib.sha256).hexdigest()


def create_session(api_token: str) -> str:
    payload = f"v1.{int(time.time()) + SESSION_SECONDS}.{secrets.token_urlsafe(32)}"
    return f"{payload}.{_signature(payload, api_token)}"


def valid_session(value: str | None, api_token: str) -> bool:
    if not value or len(value) > 140:
        return False
    match = _FORMAT.fullmatch(value)
    now = time.time()
    if match is None or not now < int(match[1]) <= now + SESSION_SECONDS:
        return False
    payload, signature = value.rsplit(".", 1)
    return hmac.compare_digest(signature, _signature(payload, api_token))
