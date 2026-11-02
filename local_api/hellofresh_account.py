#!/usr/bin/env python3
"""Read-only HelloFresh Norway account connector.

The account password reaches this trusted-LAN service for one first-use request,
is forwarded to HelloFresh through a Chrome-fingerprinted TLS connection and is
never stored.  Only allowlisted renewable tokens are written to an owner-only
local file so login survives Portal and machine restarts.  This module
intentionally has no meal-selection, delivery, subscription, address or payment
mutation methods.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import tempfile
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
    _safe_image_url,
)


BASE_URL = "https://www.hellofresh.no"
COUNTRY = "NO"
LOCALE = "nb-NO"
BRAND = "BRAND_HELLOFRESH"
MAX_JSON_BYTES = 4_000_000
MAX_HTML_BYTES = 8_000_000
TOKEN = re.compile(r"^[A-Za-z0-9_-]{8,4096}(?:\.[A-Za-z0-9_-]{8,4096}){0,2}$")
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


class HelloFreshAccountClient:
    """Transient first-use login and curated account reads for Norway."""

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
            "read_only": True,
        }

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_value: dict[str, Any] | None = None,
        bearer: str | None = None,
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
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> Any:
        credentials = self._load()
        access = _token(credentials.get("access_token"))
        if not access or _number(credentials.get("expires_at")) <= time.time() + 30:
            credentials = self._refresh(credentials)
            access = _token(credentials.get("access_token"))
        try:
            return self._request_json(path, params=params, bearer=access)
        except _HttpError as exc:
            if exc.challenge or exc.status not in {401, 403}:
                raise HelloFreshAccountUnavailable(
                    "HelloFresh-kontoen svarer ikke akkurat nå."
                ) from exc
            credentials = self._refresh(credentials)
            try:
                return self._request_json(
                    path,
                    params=params,
                    bearer=_token(credentials.get("access_token")),
                )
            except _HttpError as retry_exc:
                if retry_exc.challenge:
                    raise HelloFreshAccountUnavailable(
                        "HelloFresh-kontoen svarer ikke akkurat nå."
                    ) from retry_exc
                if retry_exc.status in {401, 403}:
                    self.disconnect()
                    raise HelloFreshAccountAuthRequired(
                        "Koble HelloFresh-kontoen til på nytt."
                    ) from retry_exc
                raise HelloFreshAccountUnavailable(
                    "HelloFresh-kontoen svarer ikke akkurat nå."
                ) from retry_exc

    @staticmethod
    def _normalize_meal(meal: Any) -> dict[str, Any] | None:
        if not isinstance(meal, dict) or not isinstance(meal.get("recipe"), dict):
            return None
        recipe = meal["recipe"]
        recipe_id = str(recipe.get("id", ""))
        name = _bounded_text(recipe.get("name"), 120)
        if not RECIPE_ID.fullmatch(recipe_id) or not name:
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
            "position": int(meal.get("index")) if isinstance(meal.get("index"), int) else 999,
            "name": name,
            "headline": _bounded_text(recipe.get("headline"), 180),
            "image_url": _safe_image_url(recipe.get("imageLink")),
            "prep_time": _bounded_text(recipe.get("prepTime") or recipe.get("totalTime"), 20),
            "difficulty": int(recipe.get("difficulty")) if recipe.get("difficulty") in {1, 2, 3} else None,
            "calories": _calories(recipe.get("nutrition")),
            "tags": tags[:6],
            "sold_out": meal.get("isSoldOut") is True,
            "extra_charge_ore": extra_charge,
            "selected_quantity": _selection_quantity(meal.get("selection")),
        }

    def menu(self, week: str) -> dict[str, Any]:
        if not isinstance(week, str) or not ISO_WEEK.fullmatch(week):
            raise HelloFreshAccountValidation("Ugyldig HelloFresh-uke.")
        info = self._authorized_json(
            "/gw/api/customers/me/info",
            params={"country": COUNTRY, "locale": LOCALE},
        )
        if not isinstance(info, dict):
            raise HelloFreshAccountUnavailable("HelloFresh-kontoen svarte i et ukjent format.")
        subscription_id = info.get("activeSubscriptionId")
        product_sku = _first_string(info.get("activeSubscriptionSkus"))
        if not isinstance(subscription_id, (str, int)) or not str(subscription_id).strip():
            raise HelloFreshAccountUnavailable("Fant ikke et aktivt HelloFresh-abonnement.")
        params: dict[str, Any] = {
            "week": week,
            "country": COUNTRY.lower(),
            "locale": LOCALE,
            "subscription": str(subscription_id),
        }
        if product_sku:
            params["product-sku"] = product_sku
        data = self._authorized_json("/gw/my-deliveries/menu", params=params)
        payload = data.get("menu", data) if isinstance(data, dict) else None
        if not isinstance(payload, dict):
            raise HelloFreshAccountUnavailable("HelloFresh-menyen svarte i et ukjent format.")
        response_week = payload.get("week") or week
        if not isinstance(response_week, str) or not ISO_WEEK.fullmatch(response_week):
            raise HelloFreshAccountUnavailable("HelloFresh returnerte ingen gyldig kontouke.")
        raw_meals = payload.get("meals") or payload.get("courses") or []
        if not isinstance(raw_meals, list):
            raise HelloFreshAccountUnavailable("HelloFresh returnerte ingen kontomeny.")
        recipes = []
        seen = set()
        for raw in raw_meals[:160]:
            recipe = self._normalize_meal(raw)
            if recipe and recipe["id"] not in seen:
                seen.add(recipe["id"])
                recipes.append(recipe)
        if not recipes:
            raise HelloFreshAccountUnavailable("HelloFresh returnerte ingen retter for denne uken.")
        recipes.sort(key=lambda item: (item["position"], item["name"]))
        return {
            "provider": "HelloFresh Norge",
            "country": COUNTRY,
            "locale": LOCALE,
            "week": response_week,
            "read_only": True,
            "account": True,
            "stale": False,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "selected_count": sum(item["selected_quantity"] for item in recipes),
            "recipes": recipes,
        }

    def disconnect(self) -> None:
        try:
            self.credentials_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise HelloFreshAccountUnavailable(
                "HelloFresh-tilkoblingen kunne ikke fjernes."
            ) from exc
