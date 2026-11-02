#!/usr/bin/env python3
"""Credential-exchange, read-only HelloFresh Norway account connector.

The supplied account password is exchanged once and is never stored.  The
browser never receives provider tokens or raw account payloads.  Refresh
credentials are stored in an owner-only local file so a completed first-use
login survives Portal and machine restarts.  This module intentionally has no
meal-selection, delivery, subscription, address or payment mutation methods.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

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
EMAIL = re.compile(r"^[^\s@]{1,120}@[^\s@]{1,190}\.[^\s@]{2,63}$")
TOKEN = re.compile(r"^[A-Za-z0-9_-]{8,4096}(?:\.[A-Za-z0-9_-]{8,4096}){0,2}$")
MAX_PASSWORD_CHARS = 512


class HelloFreshAccountValidation(ValueError):
    """The local HelloFresh account request is invalid."""


class HelloFreshAccountAuthRequired(RuntimeError):
    """The HelloFresh account needs a new login."""


class HelloFreshAccountUnavailable(RuntimeError):
    """The HelloFresh account service is temporarily unavailable."""


class _HttpError(RuntimeError):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


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
    """Transient password login and curated account reads for Norway."""

    def __init__(
        self,
        credentials_path: Path | None = None,
        *,
        timeout: int = 20,
    ) -> None:
        self.credentials_path = credentials_path or Path(
            os.environ.get(
                "FAMILYBOT_HELLOFRESH_CREDENTIALS",
                str(Path.home() / ".openclaw/credentials/hellofresh-no.json"),
            )
        ).expanduser()
        self.timeout = timeout

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
        headers = {
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
            exc.read(4096)
            raise _HttpError(exc.code) from exc
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

    def login(self, email: Any, password: Any) -> dict[str, Any]:
        """Exchange credentials once, persist tokens only, and discard the password."""
        if not isinstance(email, str) or not EMAIL.fullmatch(email.strip()):
            raise HelloFreshAccountValidation("Skriv inn en gyldig e-postadresse.")
        if (
            not isinstance(password, str)
            or not password
            or len(password) > MAX_PASSWORD_CHARS
            or "\x00" in password
        ):
            raise HelloFreshAccountValidation("Skriv inn HelloFresh-passordet.")
        try:
            tokens = self._request_json(
                "/gw/login",
                method="POST",
                params={"country": COUNTRY, "locale": LOCALE},
                json_value={"username": email.strip().lower(), "password": password},
                bearer=self._guest_token(),
            )
        except _HttpError as exc:
            if exc.status in {400, 401, 403, 404, 422}:
                raise HelloFreshAccountAuthRequired(
                    "E-post eller passord ble ikke godtatt av HelloFresh."
                ) from exc
            raise HelloFreshAccountUnavailable(
                "HelloFresh-innloggingen svarer ikke akkurat nå."
            ) from exc
        if not isinstance(tokens, dict) or not _token(tokens.get("access_token")):
            raise HelloFreshAccountAuthRequired(
                "HelloFresh returnerte ingen kontotilgang."
            )
        refresh = _token(tokens.get("refresh_token"))
        credentials = {
            "access_token": tokens["access_token"],
            "expires_at": time.time()
            + max(60, int(_number(tokens.get("expires_in"), 1800))),
        }
        if refresh:
            credentials["refresh_token"] = refresh
        self._save(credentials)
        return self.status()

    def _refresh(self, credentials: dict[str, Any]) -> dict[str, Any]:
        refresh = _token(credentials.get("refresh_token"))
        if not refresh:
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
            raise HelloFreshAccountAuthRequired("Koble HelloFresh-kontoen til på nytt.") from exc
        if not isinstance(tokens, dict) or not _token(tokens.get("access_token")):
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
            if exc.status not in {401, 403}:
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
                if retry_exc.status in {401, 403}:
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
