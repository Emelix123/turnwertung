"""Admin-Authentifizierung ueber ein signiertes Cookie (HMAC, keine Extra-Deps)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

from .config import ADMIN_COOKIE, ADMIN_PASSWORD, ADMIN_SESSION_TTL, SECRET_KEY


def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def check_password(password: str) -> bool:
    return hmac.compare_digest(password or "", ADMIN_PASSWORD)


def issue_token() -> str:
    """Token der Form <expiry>.<signatur>, base64-verpackt."""
    expiry = str(int(time.time()) + ADMIN_SESSION_TTL)
    raw = f"{expiry}.{_sign(expiry)}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        expiry, signature = raw.split(".", 1)
    except Exception:
        return False
    if not hmac.compare_digest(signature, _sign(expiry)):
        return False
    try:
        return int(expiry) > time.time()
    except ValueError:
        return False


def is_admin_request(cookies: dict) -> bool:
    return verify_token(cookies.get(ADMIN_COOKIE))
