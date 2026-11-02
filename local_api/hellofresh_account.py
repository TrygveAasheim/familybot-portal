#!/usr/bin/env python3
"""Bounded HelloFresh Norway account connector.

The account password reaches this trusted-LAN service for one first-use request,
is forwarded to HelloFresh through a Chrome-fingerprinted TLS connection and is
never stored.  Only allowlisted renewable tokens are written to an owner-only
local file so login survives Portal and machine restarts.  Account reads expose
a curated weekly-menu contract.  The only provider writes are explicit,
snapshot-guarded meal selection and week pause/resume operations; address,
payment, subscription-plan and checkout mutations remain absent.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    from curl_cffi import CurlOpt as _CurlOpt
    from curl_cffi.requests import Session as _BrowserSession
    from curl_cffi.requests.errors import RequestsError as _BrowserRequestError
except ImportError:  # Unit tests run on the macOS system Python; deployment uses its venv.
    _CurlOpt = None
    _BrowserSession = None
    _BrowserRequestError = OSError

from hellofresh_norway import (
    ISO_WEEK,
    RECIPE_ID,
    _bounded_text,
    _calories,
    _meal_categories,
    _safe_image_url,
)


BASE_URL = "https://www.hellofresh.no"
COUNTRY = "NO"
LOCALE = "nb-NO"
BRAND = "BRAND_HELLOFRESH"
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


def _first_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()[:200]
    if isinstance(value, list):
        for item in value[:20]:
            found = _first_string(item)
            if found:
                return found
    if isinstance(value, dict):
        for item in list(value.values())[:20]:
            found = _first_string(item)
            if found:
                return found
    return None


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
    if not 0 <= amount <= 100_000 or amount != amount or amount in {float("inf"), float("-inf")}:
        return None
    return int(amount) if amount.is_integer() else round(amount, 2)


class HelloFreshAccountClient:
    """Transient login plus bounded Norwegian meal and week management."""

    def __init__(
        self,
        credentials_path: Path | None = None,
        *,
        timeout: int = 20,
        browser_session_factory: Any | None = None,
    ) -> None:
        self.credentials_path = credentials_path or Path(
            os.environ.get(
                "FAMILYBOT_HELLOFRESH_CREDENTIALS",
                str(Path.home() / ".openclaw/credentials/hellofresh-no.json"),
            )
        ).expanduser()
        self.timeout = timeout
        self._browser_session_factory = browser_session_factory
        self._mutation_lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        try:
            mode = stat.S_IMODE(self.credentials_path.stat().st_mode)
            if mode != 0o600:
                raise HelloFreshAccountUnavailable(
                    "HelloFresh-tilkoblingen har utrygge filrettigheter."
                )
            value = json.loads(self.credentials_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as exc:
            raise HelloFreshAccountUnavailable(
                "HelloFresh-tilkoblingen kunne ikke leses."
            ) from exc
        except OSError as exc:
            raise HelloFreshAccountUnavailable(
                "HelloFresh-tilkoblingen kunne ikke leses."
            ) from exc

    def _save(self, value: dict[str, Any]) -> None:
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.credentials_path.parent, 0o700)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".hellofresh-no-", dir=str(self.credentials_path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.credentials_path)
            os.chmod(self.credentials_path, 0o600)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def status(self) -> dict[str, Any]:
        credentials = self._load()
        access_valid = bool(_token(credentials.get("access_token"))) and _number(
            credentials.get("expires_at")
        ) > time.time() + 30
        connected = access_valid or bool(_token(credentials.get("refresh_token")))
        return {
            "connected": connected,
            "credentials_local": True,
            "read_only": False,
            "allowed_writes": ["meal_selection", "week_pause"],
        }

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_value: dict[str, Any] | None = None,
        bearer: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        query = urllib.parse.urlencode(params or {})
        url = f"{BASE_URL}{path}{'?' + query if query else ''}"
        headers: dict[str, str] = {
            "Accept": "application/json",
            "Accept-Language": "nb-NO,nb;q=0.9",
            "User-Agent": "FamilyBot-Portal/1.0 (HelloFresh Norway account connector)",
        }
        body = None
        if json_value is not None:
            body = json.dumps(json_value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        headers.update(extra_headers or {})
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_JSON_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raw_error = exc.read(4096)
            content_type = exc.headers.get_content_type() if exc.headers else ""
            provider_code = None
            if content_type == "application/json":
                try:
                    error_value = json.loads(raw_error.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    error_value = None
                if isinstance(error_value, dict):
                    for key in ("error", "error_code", "code"):
                        candidate = error_value.get(key)
                        if isinstance(candidate, str) and ERROR_CODE.fullmatch(candidate):
                            provider_code = candidate
                            break
            challenge = content_type == "text/html" and any(
                marker in raw_error.lower()
                for marker in (b"attention required", b"cf-chl", b"challenge-platform", b"just a moment")
            )
            raise _HttpError(exc.code, code=provider_code, challenge=challenge) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HelloFreshAccountUnavailable(
                "HelloFresh-kontoen svarer ikke akkurat nå."
            ) from exc
        if len(raw) > MAX_JSON_BYTES:
            raise HelloFreshAccountUnavailable("HelloFresh-svaret var større enn forventet.")
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HelloFreshAccountUnavailable(
                "HelloFresh-kontoen svarte i et ukjent format."
            ) from exc

    def _guest_token(self) -> str:
        request = urllib.request.Request(
            f"{BASE_URL}/login",
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "nb-NO,nb;q=0.9",
                "User-Agent": "FamilyBot-Portal/1.0 (HelloFresh Norway account connector)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_HTML_BYTES + 1)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HelloFreshAccountUnavailable(
                "HelloFresh-innloggingen svarer ikke akkurat nå."
            ) from exc
        if len(raw) > MAX_HTML_BYTES:
            raise HelloFreshAccountUnavailable("HelloFresh-innloggingen var større enn forventet.")
        try:
            html = raw.decode("utf-8")
            match = re.search(
                r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
                html,
                re.DOTALL,
            )
            data = json.loads(match.group(1)) if match else {}
            value = data["props"]["pageProps"]["ssrPayload"]["serverAuth"]["access_token"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise HelloFreshAccountUnavailable(
                "HelloFresh-innloggingen manglet forventet sikkerhetsinformasjon."
            ) from exc
        token = _token(value)
        if not token:
            raise HelloFreshAccountUnavailable(
                "HelloFresh-innloggingen manglet forventet sikkerhetsinformasjon."
            )
        return token

    @staticmethod
    def _validated_email(value: Any) -> str:
        email = value.strip().lower() if isinstance(value, str) else ""
        if not EMAIL.fullmatch(email):
            raise HelloFreshAccountValidation("Skriv inn en gyldig e-postadresse.")
        return email

    @staticmethod
    def _validated_password(value: Any) -> str:
        if not isinstance(value, str) or not value or len(value) > PASSWORD_MAX_LENGTH:
            raise HelloFreshAccountValidation("Skriv inn HelloFresh-passordet.")
        return value

    @staticmethod
    def _browser_headers(*, login: bool) -> dict[str, str | None]:
        trace_id = secrets.token_hex(16)
        span_id = secrets.token_hex(8)
        headers: dict[str, str | None] = {
            "Accept": "application/json, text/plain, */*" if login else "*/*",
            "Accept-Language": "nb-NO,nb;q=0.9,en-US;q=0.8,en;q=0.7",
            "User-Agent": CHROME_USER_AGENT,
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/login",
            "Priority": "u=1, i",
            "sec-ch-ua": CHROME_SEC_UA,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "DPR": "1",
            "Viewport-Width": "1280",
            "traceparent": f"00-{trace_id}-{span_id}-01",
            "x-b3-traceid": trace_id,
            "x-b3-spanid": span_id,
            "x-b3-sampled": "1",
        }
        # curl otherwise labels an empty POST as form data; a browser fetch with
        # no body sends no Content-Type at all.
        headers["Content-Type"] = "application/json" if login else None
        return headers

    def _new_browser_session(self) -> Any:
        if self._browser_session_factory is not None:
            return self._browser_session_factory()
        if _BrowserSession is None:
            raise HelloFreshAccountUnavailable(
                "HelloFresh-innloggingen mangler nettlesertransport på Familieportalens Mac."
            )
        options = {}
        header_order = getattr(_CurlOpt, "HTTPHEADER_ORDER", None)
        if header_order is not None:
            options["curl_options"] = {header_order: LOGIN_HEADER_ORDER}
        return _BrowserSession(**options)

    @staticmethod
    def _response_payload(response: Any) -> dict[str, Any]:
        raw = bytes(response.content)
        if len(raw) > MAX_JSON_BYTES:
            raise HelloFreshAccountUnavailable("HelloFresh-svaret var større enn forventet.")
        content_type = str(response.headers.get("content-type", "")).lower()
        lowered = raw[:8192].lower()
        if "text/html" in content_type and any(
            marker in lowered
            for marker in (b"attention required", b"cf-chl", b"challenge-platform", b"just a moment")
        ):
            raise HelloFreshAccountUnavailable(
                "HelloFresh stoppet innloggingen i en sikkerhetskontroll. Vent litt før du prøver igjen."
            )
        if "application/json" not in content_type:
            raise HelloFreshAccountUnavailable(
                "HelloFresh svarte i et ukjent format under innloggingen."
            )
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HelloFreshAccountUnavailable(
                "HelloFresh svarte i et ukjent format under innloggingen."
            ) from exc
        return value if isinstance(value, dict) else {}

    def _provider_login(self, email: str, password: str) -> dict[str, Any]:
        session = self._new_browser_session()
        try:
            # The current web client performs this anonymous request before /gw/login.
            # Its result is intentionally discarded; the cookie/session priming is useful.
            prime = session.post(
                f"{BASE_URL}/gw/auth/token",
                params={"client_id": GW_CLIENT_ID, "grant_type": "client_credentials"},
                headers=self._browser_headers(login=False),
                impersonate="chrome",
                default_headers=False,
                timeout=self.timeout,
                verify=True,
            )
            if str(prime.headers.get("content-type", "")).lower().startswith("text/html"):
                self._response_payload(prime)
            response = session.post(
                f"{BASE_URL}/gw/login",
                params={"country": COUNTRY, "locale": LOCALE},
                json={"username": email, "password": password},
                headers=self._browser_headers(login=True),
                impersonate="chrome",
                default_headers=False,
                timeout=self.timeout,
                verify=True,
            )
        except _BrowserRequestError:
            raise HelloFreshAccountUnavailable(
                "HelloFresh-innloggingen svarer ikke akkurat nå."
            ) from None
        finally:
            try:
                session.close()
            except Exception:  # noqa: BLE001 - close must not replace the provider result.
                pass
        payload = self._response_payload(response)
        status = int(response.status_code)
        code = payload.get("error") if isinstance(payload.get("error"), str) else None
        if status == 429:
            raise HelloFreshAccountUnavailable(
                "HelloFresh har midlertidig sperret nye innloggingsforsøk. Vent før du prøver igjen."
            )
        if status >= 400:
            if code == "access_denied_password_must_be_rotated":
                raise HelloFreshAccountValidation(
                    "HelloFresh krever at passordet fornyes på hellofresh.no før kontoen kan kobles til."
                )
            if code in {"access_denied", "invalid_grant"}:
                raise HelloFreshAccountValidation(
                    "E-post eller passord ble ikke godtatt av HelloFresh."
                )
            if status in {401, 403}:
                raise HelloFreshAccountUnavailable(
                    "HelloFresh avviste innloggingskanalen før passordet kunne kontrolleres."
                )
            raise HelloFreshAccountUnavailable(
                "HelloFresh kunne ikke fullføre innloggingen akkurat nå."
            )
        return payload

    def login(self, payload: Any) -> dict[str, Any]:
        """Perform one transient provider login and persist only renewable tokens."""
        if not isinstance(payload, dict):
            raise HelloFreshAccountValidation("HelloFresh-innloggingen manglet nødvendig informasjon.")
        email = self._validated_email(payload.get("email"))
        password = self._validated_password(payload.get("password"))
        try:
            tokens = self._provider_login(email, password)
        finally:
            password = ""
        return self.complete_login(tokens)

    def complete_login(self, tokens: Any) -> dict[str, Any]:
        """Persist the allowlisted result of a successful direct provider login."""
        if not isinstance(tokens, dict):
            raise HelloFreshAccountValidation("HelloFresh returnerte ingen kontotilgang.")
        access = _token(tokens.get("access_token"))
        refresh = _token(tokens.get("refresh_token"))
        if not access or not refresh:
            raise HelloFreshAccountValidation("HelloFresh returnerte ingen fornybar kontotilgang.")
        credentials = {
            "access_token": access,
            "expires_at": time.time()
            + max(60, min(86_400, int(_number(tokens.get("expires_in"), 1800)))),
            "refresh_token": refresh,
        }
        self._save(credentials)
        return self.status()

    def _refresh(self, credentials: dict[str, Any]) -> dict[str, Any]:
        refresh = _token(credentials.get("refresh_token"))
        if not refresh:
            self.disconnect()
            raise HelloFreshAccountAuthRequired("Koble HelloFresh-kontoen til på nytt.")
        try:
            tokens = self._request_json(
                "/gw/refresh",
                method="POST",
                params={"country": COUNTRY, "locale": LOCALE},
                json_value={"refresh_token": refresh},
                bearer=self._guest_token(),
            )
        except _HttpError as exc:
            if exc.code in AUTH_REJECTION_CODES or (
                exc.status in {400, 401, 422} and not exc.challenge
            ):
                self.disconnect()
                raise HelloFreshAccountAuthRequired(
                    "HelloFresh-tilgangen er utløpt. Logg inn på nytt."
                ) from exc
            raise HelloFreshAccountUnavailable(
                "HelloFresh-kontoen svarer ikke akkurat nå."
            ) from exc
        if not isinstance(tokens, dict) or not _token(tokens.get("access_token")):
            self.disconnect()
            raise HelloFreshAccountAuthRequired("Koble HelloFresh-kontoen til på nytt.")
        credentials["access_token"] = tokens["access_token"]
        replacement = _token(tokens.get("refresh_token"))
        if replacement:
            credentials["refresh_token"] = replacement
        credentials["expires_at"] = time.time() + max(60, int(_number(tokens.get("expires_in"), 1800)))
        self._save(credentials)
        return credentials

    def _authorized_json(
        self,
        path: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_value: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        credentials = self._load()
        access = _token(credentials.get("access_token"))
        if not access or _number(credentials.get("expires_at")) <= time.time() + 30:
            credentials = self._refresh(credentials)
            access = _token(credentials.get("access_token"))
        try:
            return self._request_json(
                path,
                method=method,
                params=params,
                json_value=json_value,
                bearer=access,
                extra_headers=extra_headers,
            )
        except _HttpError as exc:
            if exc.challenge or exc.status != 401:
                raise HelloFreshAccountUnavailable(
                    "HelloFresh-kontoen svarer ikke akkurat nå."
                ) from exc
            credentials = self._refresh(credentials)
            try:
                return self._request_json(
                    path,
                    method=method,
                    params=params,
                    json_value=json_value,
                    bearer=_token(credentials.get("access_token")),
                    extra_headers=extra_headers,
                )
            except _HttpError as retry_exc:
                if retry_exc.challenge:
                    raise HelloFreshAccountUnavailable(
                        "HelloFresh-kontoen svarer ikke akkurat nå."
                    ) from retry_exc
                if retry_exc.status == 401:
                    self.disconnect()
                    raise HelloFreshAccountAuthRequired(
                        "Koble HelloFresh-kontoen til på nytt."
                    ) from retry_exc
                raise HelloFreshAccountUnavailable(
                    "HelloFresh-kontoen svarer ikke akkurat nå."
                ) from retry_exc

    @staticmethod
    def _week_monday(week: str) -> dt.date:
        if not isinstance(week, str) or not ISO_WEEK.fullmatch(week):
            raise HelloFreshAccountValidation("Ugyldig HelloFresh-uke.")
        year, number = week.split("-W", 1)
        try:
            return dt.date.fromisocalendar(int(year), int(number), 1)
        except ValueError as exc:
            raise HelloFreshAccountValidation("Ugyldig HelloFresh-uke.") from exc

    @classmethod
    def _shift_week(cls, week: str, count: int) -> str:
        shifted = cls._week_monday(week) + dt.timedelta(weeks=count)
        year, number, _ = shifted.isocalendar()
        return f"{year}-W{number:02d}"

    @staticmethod
    def _future_cutoff(value: Any) -> bool:
        if not isinstance(value, str) or not value:
            return False
        try:
            cutoff = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if cutoff.tzinfo is None:
                cutoff = cutoff.astimezone()
        except ValueError:
            return False
        return cutoff > dt.datetime.now().astimezone()

    def _active_subscription(self) -> dict[str, Any]:
        value = self._authorized_json("/gw/api/customers/me/subscriptions")
        items = value.get("items") if isinstance(value, dict) else None
        if not isinstance(items, list):
            raise HelloFreshAccountUnavailable("Fant ikke HelloFresh-abonnementet.")
        active = next(
            (
                item
                for item in items
                if isinstance(item, dict)
                and item.get("isActive") is True
                and not item.get("canceledAt")
            ),
            None,
        )
        if not isinstance(active, dict):
            raise HelloFreshAccountUnavailable("Fant ikke et aktivt HelloFresh-abonnement.")
        if not str(active.get("id", "")).strip():
            raise HelloFreshAccountUnavailable("HelloFresh-abonnementet mangler identifikator.")
        return active

    def _delivery_weeks(self, start: str, end: str) -> list[dict[str, Any]]:
        self._week_monday(start)
        self._week_monday(end)
        value = self._authorized_json(
            "/gw/api/customers/me/deliveries",
            params={"rangeStart": start, "rangeEnd": end},
        )
        items = value.get("items") if isinstance(value, dict) else None
        if not isinstance(items, list):
            raise HelloFreshAccountUnavailable("HelloFresh-ukene kunne ikke leses.")
        return [item for item in items if isinstance(item, dict)]

    def _delivery_week(self, week: str) -> dict[str, Any]:
        match = next(
            (
                item
                for item in self._delivery_weeks(
                    self._shift_week(week, -1), self._shift_week(week, 1)
                )
                if item.get("id") == week
            ),
            None,
        )
        if not isinstance(match, dict):
            raise HelloFreshAccountValidation("HelloFresh-uken finnes ikke på abonnementet.")
        return match

    @staticmethod
    def _assert_subscription_delivery(
        subscription: dict[str, Any], delivery: dict[str, Any]
    ) -> None:
        subscription_id = str(subscription.get("id", "")).strip()
        delivery_subscription_id = str(delivery.get("subscriptionId", "")).strip()
        if not subscription_id or delivery_subscription_id != subscription_id:
            raise HelloFreshAccountUnavailable(
                "HelloFresh-uken tilhører ikke det aktive abonnementet."
            )

    @classmethod
    def _week_snapshot(cls, week: dict[str, Any]) -> str:
        value = {
            "week": week.get("id"),
            "status": week.get("status"),
            "delivery_date": week.get("deliveryDate"),
            "cutoff": week.get("cutoffDate"),
            "blocked": week.get("deliveryBlocked") is True,
        }
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _normalize_week(cls, week: dict[str, Any], latest_menu: str | None) -> dict[str, Any]:
        actions = week.get("allowedActions") if isinstance(week.get("allowedActions"), dict) else {}
        product = week.get("product") if isinstance(week.get("product"), dict) else {}
        specs = product.get("specs") if isinstance(product.get("specs"), dict) else {}
        week_id = str(week.get("id", ""))
        status = str(week.get("status") or "UNKNOWN")
        blocked = week.get("deliveryBlocked") is True
        before_cutoff = cls._future_cutoff(week.get("cutoffDate"))
        published = False
        if ISO_WEEK.fullmatch(week_id) and isinstance(latest_menu, str) and ISO_WEEK.fullmatch(latest_menu):
            published = cls._week_monday(week_id) <= cls._week_monday(latest_menu)
        return {
            "week": week_id,
            "delivery_date": _bounded_text(week.get("deliveryDate"), 40),
            "cutoff_at": _bounded_text(week.get("cutoffDate"), 40),
            "status": status,
            "state": _bounded_text(week.get("state"), 30),
            "paused": status == "PAUSED",
            "blocked": blocked,
            "menu_published": published,
            "meal_count": int(specs.get("meals")) if isinstance(specs.get("meals"), int) else None,
            "servings": int(specs.get("size")) if isinstance(specs.get("size"), int) else None,
            "can_edit_meals": status == "RUNNING" and not blocked and before_cutoff and actions.get("mealSwap") is True,
            "can_pause": status == "RUNNING" and not blocked and before_cutoff and actions.get("pause") is True,
            "can_resume": status == "PAUSED" and not blocked and before_cutoff and actions.get("mealSwap") is True,
            "snapshot": cls._week_snapshot(week),
        }

    def weeks(self) -> dict[str, Any]:
        subscription = self._active_subscription()
        today = dt.date.today().isocalendar()
        current_week = f"{today.year}-W{today.week:02d}"
        next_modifiable = subscription.get("nextModifiableDeliveryWeek")
        start = next_modifiable if isinstance(next_modifiable, str) and ISO_WEEK.fullmatch(next_modifiable) else current_week
        latest = subscription.get("weekWithLatestMenu")
        latest_menu = latest if isinstance(latest, str) and ISO_WEEK.fullmatch(latest) else None
        # The deliveries endpoint treats rangeStart as an exclusive boundary.
        # Bracket the first requested week so nextModifiableDeliveryWeek is not
        # silently omitted from the customer journey.
        raw_weeks = self._delivery_weeks(
            self._shift_week(start, -1), self._shift_week(start, 11)
        )
        normalized = [self._normalize_week(item, latest_menu) for item in raw_weeks]
        start_date = self._week_monday(start)
        normalized = [
            item
            for item in normalized
            if ISO_WEEK.fullmatch(item["week"])
            and self._week_monday(item["week"]) >= start_date
        ]
        normalized.sort(key=lambda item: self._week_monday(item["week"]))
        default_week = next(
            (
                item["week"]
                for item in normalized
                if item["week"] == start and item["menu_published"]
            ),
            next((item["week"] for item in normalized if item["menu_published"]), ""),
        )
        return {
            "default_week": default_week,
            "latest_menu_week": latest_menu,
            "weeks": normalized,
        }

    def _product_options(self, subscription_id: str, servings: int | None) -> dict[int, str]:
        value = self._authorized_json(
            f"/gw/api/subscriptions/{urllib.parse.quote(subscription_id, safe='')}/product_options",
            params={"country": COUNTRY, "locale": LOCALE},
        )
        families = value.get("items") if isinstance(value, dict) else None
        result: dict[int, str] = {}
        for family in families if isinstance(families, list) else []:
            products = family.get("products") if isinstance(family, dict) else None
            for product in products if isinstance(products, list) else []:
                if (
                    not isinstance(product, dict)
                    or product.get("isActive") is not True
                    or product.get("isSubscribable") is not True
                ):
                    continue
                specs = product.get("specs") if isinstance(product.get("specs"), dict) else {}
                meals = specs.get("meals")
                size = specs.get("size")
                handle = product.get("handle")
                if (
                    isinstance(meals, int)
                    and 1 <= meals <= 20
                    and (servings is None or size == servings)
                    and isinstance(handle, str)
                    and 1 <= len(handle) <= 160
                ):
                    result[meals] = handle
        return result

    def _raw_menu(
        self,
        week: str,
        subscription: dict[str, Any],
        delivery: dict[str, Any],
        *,
        product_handle: str | None = None,
    ) -> dict[str, Any]:
        subscription_id = str(subscription.get("id", ""))
        product = delivery.get("product") if isinstance(delivery.get("product"), dict) else {}
        plan_product = subscription.get("product") if isinstance(subscription.get("product"), dict) else {}
        sku = product_handle or product.get("handle") or plan_product.get("sku")
        params: dict[str, Any] = {
            "week": week,
            "country": COUNTRY.lower(),
            "locale": LOCALE,
            "subscription": subscription_id,
        }
        if isinstance(sku, str) and sku:
            params["product-sku"] = sku
        value = self._authorized_json("/gw/my-deliveries/menu", params=params)
        payload = value.get("menu", value) if isinstance(value, dict) else None
        if not isinstance(payload, dict):
            raise HelloFreshAccountUnavailable("HelloFresh-menyen svarte i et ukjent format.")
        response_week = payload.get("week") or week
        if response_week != week:
            raise HelloFreshAccountUnavailable("HelloFresh returnerte feil menyuke.")
        if not isinstance(payload.get("meals"), list):
            raise HelloFreshAccountUnavailable("HelloFresh returnerte ingen kontomeny.")
        return payload

    @staticmethod
    def _normalize_meal(meal: Any, menu_order: int) -> dict[str, Any] | None:
        if not isinstance(meal, dict) or not isinstance(meal.get("recipe"), dict):
            return None
        recipe = meal["recipe"]
        recipe_id = str(recipe.get("id", ""))
        name = _bounded_text(recipe.get("name"), 120)
        course_index = meal.get("index")
        if (
            not RECIPE_ID.fullmatch(recipe_id)
            or not name
            or not isinstance(course_index, int)
            or not 0 <= course_index <= 1_000_000
        ):
            return None
        tags = []
        raw_tags = recipe.get("tags") if isinstance(recipe.get("tags"), list) else []
        for tag in raw_tags[:20]:
            if isinstance(tag, dict) and tag.get("displayLabel") is True:
                label = _bounded_text(tag.get("name"), 40)
                if label and label not in tags:
                    tags.append(label)
        charge = meal.get("charge") or meal.get("chargeSetting")
        extra_charge = None
        if isinstance(charge, dict):
            for key in ("totalAmount", "unitAmount", "amount"):
                amount = charge.get(key)
                if isinstance(amount, int) and 0 <= amount <= 100_000:
                    extra_charge = amount
                    break
        return {
            "id": recipe_id,
            "course_index": course_index,
            "position": menu_order,
            "name": name,
            "headline": _bounded_text(recipe.get("headline"), 180),
            "image_url": _safe_image_url(recipe.get("image") or recipe.get("imageLink")),
            "prep_time": _bounded_text(recipe.get("prepTime") or recipe.get("totalTime"), 20),
            "difficulty": int(recipe.get("difficulty")) if recipe.get("difficulty") in {1, 2, 3} else None,
            "calories": _calories(recipe.get("nutrition")),
            "tags": tags[:6],
            "filter_categories": _meal_categories(recipe),
            "sold_out": meal.get("isSoldOut") is True,
            "extra_charge_ore": extra_charge,
            "selected_quantity": _selection_quantity(meal.get("selection")),
        }

    @staticmethod
    def _selected_meals(payload: dict[str, Any]) -> dict[int, int]:
        selected: dict[int, int] = {}
        for meal in payload.get("meals", []):
            if not isinstance(meal, dict) or not isinstance(meal.get("index"), int):
                continue
            quantity = _selection_quantity(meal.get("selection"))
            if quantity:
                selected[meal["index"]] = quantity
        return selected

    @staticmethod
    def _preserved_extras(payload: dict[str, Any]) -> list[dict[str, Any]]:
        catalog = payload.get("addOns") if isinstance(payload.get("addOns"), dict) else {}
        groups = catalog.get("groups") if isinstance(catalog.get("groups"), list) else []
        preserved = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            entries = []
            for item in group.get("addOns", []) if isinstance(group.get("addOns"), list) else []:
                selection = item.get("selection") if isinstance(item, dict) else None
                index = item.get("index") if isinstance(item, dict) else None
                if not isinstance(selection, dict) or not isinstance(index, int):
                    continue
                one_off = int(_number(selection.get("oneOffQuantity"), 0))
                preselected = int(_number(selection.get("preselectedQuantity"), 0))
                if not (one_off or preselected or selection.get("skipped") is True):
                    continue
                courses = []
                for course in selection.get("courses", []) if isinstance(selection.get("courses"), list) else []:
                    if isinstance(course, dict) and isinstance(course.get("index"), int):
                        courses.append({"index": course["index"]})
                entries.append(
                    {
                        "index": index,
                        "oneOffQuantity": max(0, min(20, one_off)),
                        "preselectedQuantity": max(0, min(20, preselected)),
                        "courses": courses[:20],
                    }
                )
            group_type = group.get("groupType")
            sku = group.get("sku")
            if entries and isinstance(group_type, str) and isinstance(sku, str):
                preserved.append({"groupType": group_type[:80], "sku": sku[:160], "selection": entries})
        return preserved

    @classmethod
    def _menu_snapshot(
        cls,
        week: str,
        payload: dict[str, Any],
        delivery: dict[str, Any],
        product_handle: str,
    ) -> str:
        value = {
            "week": week,
            "menu": str(payload.get("id", ""))[:200],
            "meals": sorted(cls._selected_meals(payload).items()),
            "extras": cls._preserved_extras(payload),
            "product": product_handle,
            "week_state": cls._week_snapshot(delivery),
        }
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _menu_bundle(self, week: str, *, product_handle: str | None = None) -> dict[str, Any]:
        self._week_monday(week)
        subscription = self._active_subscription()
        delivery = self._delivery_week(week)
        self._assert_subscription_delivery(subscription, delivery)
        product = delivery.get("product") if isinstance(delivery.get("product"), dict) else {}
        plan_product = subscription.get("product") if isinstance(subscription.get("product"), dict) else {}
        effective_product = product_handle or product.get("handle") or plan_product.get("sku")
        if not isinstance(effective_product, str) or not effective_product:
            raise HelloFreshAccountUnavailable("HelloFresh-uken mangler matkassetype.")
        payload = self._raw_menu(
            week,
            subscription,
            delivery,
            product_handle=effective_product,
        )
        specs = product.get("specs") if isinstance(product.get("specs"), dict) else {}
        servings = specs.get("size") if isinstance(specs.get("size"), int) else None
        options = self._product_options(str(subscription["id"]), servings)
        return {
            "week": week,
            "subscription": subscription,
            "delivery": delivery,
            "payload": payload,
            "product_handle": effective_product,
            "product_options": options,
            "servings": servings,
        }

    def _menu_contract(self, bundle: dict[str, Any]) -> dict[str, Any]:
        payload = bundle["payload"]
        recipes = []
        seen_indexes = set()
        for menu_order, raw in enumerate(payload.get("meals", [])[:160]):
            recipe = self._normalize_meal(raw, menu_order)
            if recipe and recipe["course_index"] not in seen_indexes:
                seen_indexes.add(recipe["course_index"])
                recipes.append(recipe)
        if not recipes:
            raise HelloFreshAccountUnavailable("HelloFresh returnerte ingen retter for denne uken.")
        recipes.sort(key=lambda item: (item["selected_quantity"] <= 0, item["position"], item["name"]))
        delivery = bundle["delivery"]
        latest = bundle["subscription"].get("weekWithLatestMenu")
        week_state = self._normalize_week(
            delivery,
            latest if isinstance(latest, str) and ISO_WEEK.fullmatch(latest) else None,
        )
        selected_count = sum(item["selected_quantity"] for item in recipes)
        return {
            "provider": "HelloFresh Norge",
            "country": COUNTRY,
            "locale": LOCALE,
            "week": bundle["week"],
            "read_only": False,
            "account": True,
            "stale": False,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "selected_count": selected_count,
            "servings": bundle["servings"],
            "available_meal_counts": sorted(bundle["product_options"]),
            "editable": week_state["can_edit_meals"],
            "paused": week_state["paused"],
            "delivery_date": week_state["delivery_date"],
            "cutoff_at": week_state["cutoff_at"],
            "selection_snapshot": self._menu_snapshot(
                bundle["week"], payload, delivery, bundle["product_handle"]
            ),
            "recipes": recipes,
        }

    def menu(self, week: str) -> dict[str, Any]:
        return self._menu_contract(self._menu_bundle(week))

    def recipe_detail(self, recipe_id: str, servings: int | None = None) -> dict[str, Any]:
        """Return one allowlisted recipe; never expose the provider's raw object."""
        if not isinstance(recipe_id, str) or not RECIPE_ID.fullmatch(recipe_id):
            raise HelloFreshAccountValidation("Ugyldig HelloFresh-rett.")
        if servings is not None and (isinstance(servings, bool) or not 1 <= servings <= 12):
            raise HelloFreshAccountValidation("Ugyldig antall porsjoner.")
        value = self._authorized_json(
            f"/gw/recipes/recipes/{urllib.parse.quote(recipe_id, safe='')}",
            params={"country": COUNTRY, "locale": LOCALE},
        )
        if not isinstance(value, dict) or value.get("id") != recipe_id:
            raise HelloFreshAccountUnavailable("HelloFresh-oppskriften svarte i et ukjent format.")

        raw_ingredients = value.get("ingredients") if isinstance(value.get("ingredients"), list) else []
        raw_yields = value.get("yields") if isinstance(value.get("yields"), list) else []
        selected_yield = next(
            (
                item for item in raw_yields[:12]
                if isinstance(item, dict) and item.get("yields") == servings
            ),
            next((item for item in raw_yields[:12] if isinstance(item, dict)), {}),
        )
        selected_servings = selected_yield.get("yields") if isinstance(selected_yield, dict) else None
        if not isinstance(selected_servings, int) or not 1 <= selected_servings <= 12:
            selected_servings = servings
        yield_ingredients = (
            selected_yield.get("ingredients")
            if isinstance(selected_yield, dict) and isinstance(selected_yield.get("ingredients"), list)
            else []
        )
        amounts: dict[str, tuple[int | float | None, str]] = {}
        for item in yield_ingredients[:80]:
            if not isinstance(item, dict):
                continue
            ingredient_id = str(item.get("id", ""))[:200]
            if ingredient_id:
                amounts[ingredient_id] = (
                    _bounded_amount(item.get("amount")),
                    _bounded_text(item.get("unit"), 30),
                )

        referenced_allergens: set[str] = set()
        ingredients = []
        for item in raw_ingredients[:40]:
            if not isinstance(item, dict):
                continue
            name = _bounded_text(item.get("name"), 100)
            if not name:
                continue
            ingredient_id = str(item.get("id", ""))[:200]
            amount, unit = amounts.get(ingredient_id, (None, ""))
            ingredients.append(
                {
                    "name": name,
                    "amount": amount,
                    "unit": unit,
                    "shipped": item.get("shipped") is not False,
                }
            )
            for allergen in item.get("allergens", [])[:20] if isinstance(item.get("allergens"), list) else []:
                if isinstance(allergen, str) and 1 <= len(allergen) <= 200:
                    referenced_allergens.add(allergen)

        allergens = []
        may_contain = []
        raw_allergens = value.get("allergens") if isinstance(value.get("allergens"), list) else []
        for item in raw_allergens[:40]:
            if not isinstance(item, dict) or str(item.get("id", "")) not in referenced_allergens:
                continue
            name = _bounded_text(item.get("name"), 80)
            if not name or item.get("triggersTracesOf") is True:
                continue
            if item.get("tracesOf") is True and name not in may_contain:
                may_contain.append(name)
            elif name not in allergens:
                allergens.append(name)

        nutrition = []
        for item in value.get("nutrition", [])[:20] if isinstance(value.get("nutrition"), list) else []:
            if not isinstance(item, dict):
                continue
            name = _bounded_text(item.get("name"), 80)
            amount = _bounded_amount(item.get("amount"))
            if name and amount is not None:
                nutrition.append(
                    {"name": name, "amount": amount, "unit": _bounded_text(item.get("unit"), 30)}
                )

        name = _bounded_text(value.get("name"), 120)
        if not name:
            raise HelloFreshAccountUnavailable("HelloFresh-oppskriften manglet navn.")
        description = _bounded_text(value.get("description"), 1_000)
        if not any(character.isalnum() for character in description):
            description = ""
        return {
            "id": recipe_id,
            "name": name,
            "headline": _bounded_text(value.get("headline"), 180),
            "description": description,
            "image_url": _safe_image_url(value.get("image") or value.get("imageLink")),
            "prep_time": _bounded_text(value.get("prepTime"), 20),
            "total_time": _bounded_text(value.get("totalTime"), 20),
            "difficulty": int(value.get("difficulty")) if value.get("difficulty") in {1, 2, 3} else None,
            "servings": selected_servings,
            "ingredients": ingredients,
            "allergens": allergens[:24],
            "may_contain": may_contain[:24],
            "nutrition": nutrition,
        }

    @staticmethod
    def _expected_snapshot(payload: Any, key: str = "snapshot") -> str:
        value = payload.get(key) if isinstance(payload, dict) else None
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise HelloFreshAccountValidation("HelloFresh-visningen må oppdateres før endringen.")
        return value

    @staticmethod
    def _requested_course(payload: Any, key: str) -> int:
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000:
            raise HelloFreshAccountValidation("Velg en gyldig HelloFresh-rett.")
        return value

    @staticmethod
    def _meal_by_index(payload: dict[str, Any], course_index: int) -> dict[str, Any] | None:
        return next(
            (
                meal
                for meal in payload.get("meals", [])
                if isinstance(meal, dict) and meal.get("index") == course_index
            ),
            None,
        )

    @classmethod
    def _assert_meal_editable(cls, bundle: dict[str, Any]) -> None:
        subscription = bundle["subscription"]
        latest = subscription.get("weekWithLatestMenu")
        week = cls._normalize_week(
            bundle["delivery"],
            latest if isinstance(latest, str) and ISO_WEEK.fullmatch(latest) else None,
        )
        if week["paused"]:
            raise HelloFreshAccountValidation("Aktiver uken før rettene endres.")
        if not week["can_edit_meals"]:
            raise HelloFreshAccountValidation("Fristen for å endre denne matkassen er passert.")

    def _save_cart(
        self,
        bundle: dict[str, Any],
        selected: dict[int, int],
        product_handle: str,
    ) -> dict[str, Any]:
        subscription = bundle["subscription"]
        delivery = bundle["delivery"]
        customer = subscription.get("customer") if isinstance(subscription.get("customer"), dict) else {}
        customer_id = customer.get("id")
        if not isinstance(customer_id, (str, int)) or not str(customer_id).strip():
            info = self._authorized_json(
                "/gw/api/customers/me/info",
                params={"country": COUNTRY, "locale": LOCALE},
            )
            customer_id = info.get("id") if isinstance(info, dict) else None
        if not isinstance(customer_id, (str, int)) or not str(customer_id).strip():
            raise HelloFreshAccountUnavailable("HelloFresh-kontoen mangler kundeidentifikator.")
        cutoff = delivery.get("cutoffDate")
        if not isinstance(cutoff, str) or not cutoff:
            raise HelloFreshAccountValidation("HelloFresh-uken mangler endringsfrist.")
        params = {
            "subscription": str(subscription["id"]),
            "customer": str(customer_id),
            "week": bundle["week"],
            "product-sku": product_handle,
            "preference": str(subscription.get("preset") or ""),
            "cutoff_time": cutoff,
            "ignore_addons": "false",
            "update_quantity": "true",
        }
        result = self._authorized_json(
            f"/gw/v1/carts/{urllib.parse.quote(bundle['week'], safe='')}",
            method="PUT",
            params=params,
            json_value={
                "meals": [
                    {"index": index, "quantity": quantity}
                    for index, quantity in sorted(selected.items())
                ],
                "extras": self._preserved_extras(bundle["payload"]),
            },
            extra_headers={"x-requested-by": "shopping-experience-web"},
        )
        if isinstance(result, dict) and result.get("hasSeamlessDowngraded") is True:
            raise HelloFreshAccountConflict(
                "HelloFresh reduserte matkassen. Oppdater uken og kontroller valgene."
            )
        verified = self._menu_bundle(bundle["week"], product_handle=product_handle)
        if self._selected_meals(verified["payload"]) != selected:
            raise HelloFreshAccountConflict(
                "HelloFresh bekreftet ikke hele endringen. Oppdater uken før du prøver igjen."
            )
        return self._menu_contract(verified)

    def change_selection(self, week: str, payload: Any, action: str) -> dict[str, Any]:
        if action not in {"replace", "add", "remove"}:
            raise HelloFreshAccountValidation("Ukjent HelloFresh-endring.")
        with self._mutation_lock:
            bundle = self._menu_bundle(week)
            self._assert_meal_editable(bundle)
            expected = self._expected_snapshot(payload)
            actual = self._menu_snapshot(
                week,
                bundle["payload"],
                bundle["delivery"],
                bundle["product_handle"],
            )
            if not secrets.compare_digest(expected, actual):
                raise HelloFreshAccountConflict(
                    "HelloFresh-uken er endret siden den ble åpnet. Oppdater før du prøver igjen."
                )
            selected = self._selected_meals(bundle["payload"])
            if action == "replace":
                old = self._requested_course(payload, "from_course_index")
                new = self._requested_course(payload, "to_course_index")
                target = self._meal_by_index(bundle["payload"], new)
                if old not in selected or new in selected or target is None:
                    raise HelloFreshAccountValidation("Velg én valgt rett og én ny rett.")
                if target.get("isSoldOut") is True:
                    raise HelloFreshAccountValidation("Den nye retten er utsolgt.")
                quantity = selected.pop(old)
                selected[new] = quantity
            elif action == "add":
                new = self._requested_course(payload, "course_index")
                target = self._meal_by_index(bundle["payload"], new)
                if new in selected or target is None:
                    raise HelloFreshAccountValidation("Retten er allerede valgt eller finnes ikke.")
                if target.get("isSoldOut") is True:
                    raise HelloFreshAccountValidation("Retten er utsolgt.")
                selected[new] = 1
            else:
                old = self._requested_course(payload, "course_index")
                if old not in selected:
                    raise HelloFreshAccountValidation("Retten er ikke valgt i denne matkassen.")
                selected.pop(old)
            total = sum(selected.values())
            product_handle = bundle["product_options"].get(total)
            if not product_handle:
                available = ", ".join(str(value) for value in sorted(bundle["product_options"]))
                raise HelloFreshAccountValidation(
                    f"Denne matkassen støtter {available} retter."
                )
            return self._save_cart(bundle, selected, product_handle)

    def set_week_paused(self, week: str, payload: Any) -> dict[str, Any]:
        paused = payload.get("paused") if isinstance(payload, dict) else None
        if not isinstance(paused, bool):
            raise HelloFreshAccountValidation("Velg om uken skal pauses eller aktiveres.")
        expected = self._expected_snapshot(payload)
        with self._mutation_lock:
            subscription = self._active_subscription()
            delivery = self._delivery_week(week)
            self._assert_subscription_delivery(subscription, delivery)
            actual = self._week_snapshot(delivery)
            if not secrets.compare_digest(expected, actual):
                raise HelloFreshAccountConflict(
                    "HelloFresh-uken er endret siden den ble åpnet. Oppdater før du prøver igjen."
                )
            latest = subscription.get("weekWithLatestMenu")
            state = self._normalize_week(
                delivery,
                latest if isinstance(latest, str) and ISO_WEEK.fullmatch(latest) else None,
            )
            allowed = state["can_pause"] if paused else state["can_resume"]
            if not allowed:
                raise HelloFreshAccountValidation(
                    "HelloFresh tillater ikke denne endringen for valgt uke."
                )
            delivery_date = delivery.get("deliveryDate")
            if not isinstance(delivery_date, str) or not delivery_date:
                raise HelloFreshAccountValidation("HelloFresh-uken mangler leveringsdato.")
            subscription_id = str(subscription["id"])
            self._authorized_json(
                f"/gw/api/subscriptions/{urllib.parse.quote(subscription_id, safe='')}/delivery_dates/{urllib.parse.quote(week, safe='')}",
                method="PATCH",
                params={"country": COUNTRY, "locale": LOCALE},
                json_value={
                    "delivery": {
                        "id": week,
                        "status": "PAUSED" if paused else "RUNNING",
                        "deliveryDate": delivery_date,
                    }
                },
            )
            verified = self._delivery_week(week)
            if (verified.get("status") == "PAUSED") is not paused:
                raise HelloFreshAccountConflict(
                    "HelloFresh bekreftet ikke ukestatusen. Oppdater før du prøver igjen."
                )
            return self._normalize_week(
                verified,
                latest if isinstance(latest, str) and ISO_WEEK.fullmatch(latest) else None,
            )

    def disconnect(self) -> None:
        try:
            self.credentials_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise HelloFreshAccountUnavailable(
                "HelloFresh-tilkoblingen kunne ikke fjernes."
            ) from exc
