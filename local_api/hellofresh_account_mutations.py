#!/usr/bin/env python3
"""Snapshot-guarded HelloFresh meal and week mutations."""

from __future__ import annotations

import re
import secrets
import urllib.parse
from typing import Any

from hellofresh_account_contract import (
    COUNTRY,
    LOCALE,
    HelloFreshAccountConflict,
    HelloFreshAccountUnavailable,
    HelloFreshAccountValidation,
)
from hellofresh_norway import ISO_WEEK


class HelloFreshMutationMixin:
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

