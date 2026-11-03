#!/usr/bin/env python3
"""Stable security and provider-contract primitives for HelloFresh Norway."""

from __future__ import annotations

import math
import re
from typing import Any

BASE_URL = "https://www.hellofresh.no"
COUNTRY = "NO"
LOCALE = "nb-NO"
MAX_JSON_BYTES = 4_000_000
MAX_HTML_BYTES = 8_000_000
# OAuth token syntax is intentionally opaque.  Access tokens currently happen to
# be JWTs, but refresh tokens are not contractually base64url/JWT shaped and may
# contain printable punctuation such as ``+``, ``/`` or ``=``.  Keep the local
# boundary strict enough to prevent control/whitespace injection while accepting
# the provider's full opaque-token contract.
TOKEN = re.compile(r"[\x21-\x7e]{8,8192}")
ERROR_CODE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")
PASSWORD_MAX_LENGTH = 512
GW_CLIENT_ID = "senf"
CHROME_VERSION = 150  # curl_cffi 0.16.3's pinned rolling Chrome target.
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/{CHROME_VERSION}.0.0.0 Safari/537.36"
)
CHROME_SEC_UA = (
    '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"'
)
LOGIN_HEADER_ORDER = ",".join(
    (
        "content-length",
        "x-b3-spanid",
        "sec-ch-ua-platform",
        "viewport-width",
        "x-b3-sampled",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "traceparent",
        "dpr",
        "x-b3-traceid",
        "user-agent",
        "accept",
        "content-type",
        "origin",
        "sec-fetch-site",
        "sec-fetch-mode",
        "sec-fetch-dest",
        "referer",
        "accept-encoding",
        "accept-language",
        "cookie",
        "priority",
    )
)
AUTH_REJECTION_CODES = {
    "access_denied",
    "access_denied_password_must_be_rotated",
    "invalid_grant",
    "invalid_token",
}


class HelloFreshAccountValidation(ValueError):
    """The local HelloFresh account request is invalid."""


class HelloFreshAccountAuthRequired(RuntimeError):
    """The HelloFresh account needs a new login."""


class HelloFreshAccountUnavailable(RuntimeError):
    """The HelloFresh account service is temporarily unavailable."""


class HelloFreshAccountConflict(RuntimeError):
    """The requested week changed after the browser loaded it."""


class _HttpError(RuntimeError):
    def __init__(self, status: int, *, code: str | None = None, challenge: bool = False):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.code = code
        self.challenge = challenge


def _token(value: Any) -> str | None:
    return value if isinstance(value, str) and TOKEN.fullmatch(value) else None


def _selection_quantity(selection: Any) -> int:
    if isinstance(selection, bool) or selection is None:
        return 0
    if isinstance(selection, (int, float)):
        return max(0, min(20, int(selection)))
    if isinstance(selection, str) and selection.isdigit():
        return max(0, min(20, int(selection)))
    if not isinstance(selection, dict) or selection.get("skipped") is True:
        return 0
    return _selection_quantity(selection.get("quantity"))


def _number(value: Any, default: float = 0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bounded_amount(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amount) or not 0 <= amount <= 100_000:
        return None
    return int(amount) if amount.is_integer() else round(amount, 2)

PROVIDER_CONTRACT_VERSION = 1
_STATIC_PROVIDER_PATHS = frozenset(
    {
        "/gw/auth/token",
        "/gw/login",
        "/gw/refresh",
        "/gw/api/customers/me/subscriptions",
        "/gw/api/customers/me/deliveries",
        "/gw/api/customers/me/info",
        "/gw/my-deliveries/menu",
    }
)
_PROVIDER_SEGMENT = r"(?:(?:[A-Za-z0-9._~-])|(?:%[0-9A-Fa-f]{2})){1,512}"
_DYNAMIC_PROVIDER_PATHS = (
    re.compile(rf"/gw/api/subscriptions/{_PROVIDER_SEGMENT}/product_options"),
    re.compile(rf"/gw/api/subscriptions/{_PROVIDER_SEGMENT}/delivery_dates/\d{{4}}-W\d{{2}}"),
    re.compile(r"/gw/recipes/recipes/[0-9a-f]{24}"),
    re.compile(r"/gw/v1/carts/\d{4}-W\d{2}"),
)


def validate_provider_path(path: str) -> str:
    """Reject endpoint drift before any network request is constructed."""
    if path in _STATIC_PROVIDER_PATHS or any(pattern.fullmatch(path) for pattern in _DYNAMIC_PROVIDER_PATHS):
        return path
    raise HelloFreshAccountUnavailable(
        "HelloFresh-integrasjonen forsøkte et kall utenfor den godkjente kontrakten."
    )
