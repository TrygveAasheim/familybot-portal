#!/usr/bin/env python3
"""Curated HelloFresh recipe-detail projection."""

from __future__ import annotations

import urllib.parse
from typing import Any

from hellofresh_account_contract import (
    COUNTRY,
    LOCALE,
    HelloFreshAccountUnavailable,
    HelloFreshAccountValidation,
    _bounded_amount,
)
from hellofresh_norway import RECIPE_ID, _bounded_text, _safe_image_url


class HelloFreshRecipeMixin:
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

