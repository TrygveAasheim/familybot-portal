#!/usr/bin/env python3
"""Read-only adapter for the public Norwegian HelloFresh weekly menu.

This first integration slice deliberately has no account login, cookies or
mutation methods.  It extracts a small allowlisted contract from the public
Norwegian menu page and never forwards HelloFresh's embedded application state
or public bootstrap token to the browser.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
import threading
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse


BASE_URL = "https://www.hellofresh.no"
MENU_URL = f"{BASE_URL}/menus"
MAX_HTML_BYTES = 8_000_000
MAX_RECIPES = 80
CACHE_SECONDS = 15 * 60
STALE_CACHE_SECONDS = 6 * 60 * 60
RECIPE_ID = re.compile(r"^[0-9a-f]{24}$")
ISO_WEEK = re.compile(r"^\d{4}-W(?:0[1-9]|[1-4]\d|5[0-3])$")
ALLOWED_IMAGE_HOSTS = {
    "d3hvwccx09j84u.cloudfront.net",
    "cdn.hellofresh.com",
    "img.hellofresh.com",
    "media.hellofresh.com",
}


class HelloFreshUnavailable(RuntimeError):
    """The public Norwegian HelloFresh menu is temporarily unavailable."""


class _NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._capturing = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("id") == "__NEXT_DATA__":
            self._capturing = True

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capturing:
            self._capturing = False

    @property
    def value(self) -> str:
        return "".join(self._parts)


def _bounded_text(value: Any, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:maximum]


def _safe_recipe_url(value: Any, recipe_id: str) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if (
        parsed.scheme == "https"
        and parsed.hostname in {"hellofresh.no", "www.hellofresh.no"}
        and parsed.path.startswith("/recipes/")
        and parsed.path.rstrip("/").endswith(recipe_id)
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    ):
        return value
    return None


def _safe_image_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if (
        parsed.scheme == "https"
        and parsed.hostname in ALLOWED_IMAGE_HOSTS
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
    ):
        return value
    return None


def _calories(nutrition: Any) -> int | None:
    if not isinstance(nutrition, list):
        return None
    for item in nutrition[:30]:
        if not isinstance(item, dict) or str(item.get("name", "")).casefold() not in {"kalorier", "calories"}:
            continue
        amount = item.get("amount")
        if isinstance(amount, (int, float)) and 0 <= amount <= 10_000:
            return round(amount)
    return None


def _meal_categories(recipe: Any) -> list[str]:
    """Derive a small, deterministic set of family-facing menu filters."""
    if not isinstance(recipe, dict):
        return []
    values = [recipe.get("name"), recipe.get("headline")]
    for key in ("tags", "cuisines"):
        collection = recipe.get(key) if isinstance(recipe.get(key), list) else []
        for item in collection[:40]:
            if isinstance(item, dict):
                values.extend((item.get("name"), item.get("type")))
            elif isinstance(item, str):
                values.append(item)
    haystack = " ".join(value for value in values if isinstance(value, str)).casefold()
    rules = {
        "meat": (
            "kjøtt", "storfe", "biff", "okse", "svin", "bacon", "chorizo",
            "pølse", "kylling", "kalkun", "lam", "beef", "pork", "chicken",
            "turkey", "sausage", "meat",
        ),
        "fish": (
            "fisk", "laks", "ørret", "torsk", "hyse", "sei", "tunfisk",
            "reke", "scampi", "fish", "salmon", "trout", "cod", "haddock",
            "shrimp", "prawn", "seafood",
        ),
        "pasta": (
            "pasta", "spaghetti", "linguine", "tagliatelle", "tortelloni",
            "ravioli", "lasagne", "gnocchi", "orzo", "penne", "fusilli",
            "nudel", "noodle", "ramen",
        ),
        "vegetarian": ("vegetar", "veggie", "vegetarian", "vegan"),
    }
    return [key for key, needles in rules.items() if any(needle in haystack for needle in needles)]


class HelloFreshNorwayClient:
    """Fetch and normalize only public Norwegian menu information."""

    def __init__(self, *, timeout: int = 20) -> None:
        self.timeout = timeout
        self._lock = threading.RLock()
        self._cached_at = 0.0
        self._cache: dict[str, Any] | None = None

    def _fetch_html(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {"hellofresh.no", "www.hellofresh.no"}:
            raise HelloFreshUnavailable("HelloFresh-adressen ble avvist.")
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "nb-NO,nb;q=0.9",
                "User-Agent": "FamilyBot-Portal/0.1 (read-only HelloFresh Norway integration)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                final = urlparse(response.geturl())
                if final.scheme != "https" or final.hostname not in {"hellofresh.no", "www.hellofresh.no"}:
                    raise HelloFreshUnavailable("HelloFresh sendte forespørselen til et ukjent domene.")
                raw = response.read(MAX_HTML_BYTES + 1)
        except urllib.error.HTTPError as exc:
            exc.read(4096)
            raise HelloFreshUnavailable("HelloFresh-menyen svarer ikke akkurat nå.") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HelloFreshUnavailable("HelloFresh-menyen svarer ikke akkurat nå.") from exc
        if len(raw) > MAX_HTML_BYTES:
            raise HelloFreshUnavailable("HelloFresh-menyen var større enn forventet.")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HelloFreshUnavailable("HelloFresh-menyen hadde et ukjent tekstformat.") from exc

    @staticmethod
    def _next_data(html: str) -> dict[str, Any]:
        parser = _NextDataParser()
        parser.feed(html)
        if not parser.value:
            raise HelloFreshUnavailable("HelloFresh-menyen manglet forventede data.")
        try:
            value = json.loads(parser.value)
        except json.JSONDecodeError as exc:
            raise HelloFreshUnavailable("HelloFresh-menyen hadde et ukjent dataformat.") from exc
        if not isinstance(value, dict):
            raise HelloFreshUnavailable("HelloFresh-menyen hadde et ukjent dataformat.")
        return value

    @staticmethod
    def _normalize_recipe(course: Any) -> dict[str, Any] | None:
        if not isinstance(course, dict) or not isinstance(course.get("recipe"), dict):
            return None
        recipe = course["recipe"]
        recipe_id = str(recipe.get("id", ""))
        if not RECIPE_ID.fullmatch(recipe_id):
            return None
        name = _bounded_text(recipe.get("name"), 120)
        recipe_url = _safe_recipe_url(recipe.get("websiteUrl"), recipe_id)
        image_url = _safe_image_url(recipe.get("imageLink"))
        if not name or not recipe_url:
            return None
        tags = []
        for tag in recipe.get("tags", [])[:20] if isinstance(recipe.get("tags"), list) else []:
            if isinstance(tag, dict) and tag.get("displayLabel") is True:
                label = _bounded_text(tag.get("name"), 40)
                if label and label not in tags:
                    tags.append(label)
        extra_charge = course.get("chargeSetting", {}).get("amount") if isinstance(course.get("chargeSetting"), dict) else None
        return {
            "id": recipe_id,
            "course_index": int(course.get("index")) if isinstance(course.get("index"), int) else 999,
            "position": int(course.get("index")) if isinstance(course.get("index"), int) else 999,
            "name": name,
            "headline": _bounded_text(recipe.get("headline"), 180),
            "image_url": image_url,
            "prep_time": _bounded_text(recipe.get("prepTime"), 20),
            "difficulty": int(recipe.get("difficulty")) if recipe.get("difficulty") in {1, 2, 3} else None,
            "calories": _calories(recipe.get("nutrition")),
            "tags": tags[:6],
            "filter_categories": _meal_categories(recipe),
            "sold_out": course.get("isSoldOut") is True,
            "extra_charge_ore": int(extra_charge) if isinstance(extra_charge, int) and 0 <= extra_charge <= 100_000 else None,
        }

    def _read_menu(self) -> dict[str, Any]:
        data = self._next_data(self._fetch_html(MENU_URL))
        try:
            payload = data["props"]["pageProps"]["ssrPayload"]
        except (KeyError, TypeError) as exc:
            raise HelloFreshUnavailable("HelloFresh-menyen manglet forventede data.") from exc
        if not isinstance(payload, dict) or payload.get("systemCountry") != "NO" or payload.get("locale") != "nb-NO":
            raise HelloFreshUnavailable("HelloFresh returnerte ikke den norske menyen.")
        week = payload.get("activeWeek") or payload.get("currentWeek")
        if not isinstance(week, str) or not ISO_WEEK.fullmatch(week):
            raise HelloFreshUnavailable("HelloFresh returnerte ingen gyldig menyuke.")
        courses = payload.get("courses")
        if not isinstance(courses, list):
            raise HelloFreshUnavailable("HelloFresh returnerte ingen oppskrifter.")
        recipes = []
        seen = set()
        for course in courses[:MAX_RECIPES * 2]:
            recipe = self._normalize_recipe(course)
            if recipe and recipe["id"] not in seen:
                seen.add(recipe["id"])
                recipes.append(recipe)
            if len(recipes) >= MAX_RECIPES:
                break
        if not recipes:
            raise HelloFreshUnavailable("HelloFresh returnerte ingen norske oppskrifter.")
        recipes.sort(key=lambda item: (item["position"], item["name"]))
        return {
            "provider": "HelloFresh Norge",
            "country": "NO",
            "locale": "nb-NO",
            "week": week,
            "read_only": True,
            "stale": False,
            "fetched_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "recipes": recipes,
        }

    def menu(self) -> dict[str, Any]:
        with self._lock:
            age = time.monotonic() - self._cached_at
            if self._cache is not None and age < CACHE_SECONDS:
                return copy.deepcopy(self._cache)
            try:
                menu = self._read_menu()
            except HelloFreshUnavailable:
                if self._cache is None or age >= STALE_CACHE_SECONDS:
                    raise
                stale = copy.deepcopy(self._cache)
                stale["stale"] = True
                stale["warning"] = "Viser sist hentede meny fordi HelloFresh ikke svarer akkurat nå."
                return stale
            self._cache = menu
            self._cached_at = time.monotonic()
            return copy.deepcopy(menu)
