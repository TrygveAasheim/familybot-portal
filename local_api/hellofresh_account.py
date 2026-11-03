#!/usr/bin/env python3
"""Curated HelloFresh Norway account facade.

The public client stays stable while credentials/transport, menu projection,
recipe details, and snapshot-guarded writes live in focused modules.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import urllib.parse
from typing import Any

from hellofresh_account_contract import (
    COUNTRY,
    LOCALE,
    _number,
    _selection_quantity,
)
from hellofresh_account_contract import (
    HelloFreshAccountAuthRequired as HelloFreshAccountAuthRequired,
)
from hellofresh_account_contract import (
    HelloFreshAccountConflict as HelloFreshAccountConflict,
)
from hellofresh_account_contract import (
    HelloFreshAccountUnavailable as HelloFreshAccountUnavailable,
)
from hellofresh_account_contract import (
    HelloFreshAccountValidation as HelloFreshAccountValidation,
)
from hellofresh_account_contract import (
    _HttpError as _HttpError,
)
from hellofresh_account_mutations import HelloFreshMutationMixin
from hellofresh_account_recipe import HelloFreshRecipeMixin
from hellofresh_account_transport import HelloFreshTransportMixin
from hellofresh_norway import (
    ISO_WEEK,
    RECIPE_ID,
    _bounded_text,
    _calories,
    _meal_categories,
    _safe_image_url,
)


class HelloFreshAccountClient(
    HelloFreshRecipeMixin, HelloFreshMutationMixin, HelloFreshTransportMixin
):
    """Transient login plus bounded Norwegian meal and week management."""

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
