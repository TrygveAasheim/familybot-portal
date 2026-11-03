#!/usr/bin/env python3
"""Run a read-only, count-only probe of the connected HelloFresh contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "local_api"))

from hellofresh_account import HelloFreshAccountClient  # noqa: E402


def main() -> int:
    account = HelloFreshAccountClient()
    status = account.status()
    result = {
        "provider_contract_version": status.get("provider_contract_version"),
        "connected": status.get("connected") is True,
        "weeks": 0,
        "published_weeks": 0,
        "menu_checked": False,
        "recipes": 0,
        "writes_checked": False,
    }
    if not result["connected"]:
        print(json.dumps(result, sort_keys=True))
        return 2

    weeks_payload = account.weeks()
    weeks = weeks_payload.get("weeks") if isinstance(weeks_payload, dict) else None
    safe_weeks = weeks if isinstance(weeks, list) else []
    result["weeks"] = len(safe_weeks)
    published = [
        item
        for item in safe_weeks
        if isinstance(item, dict)
        and item.get("menu_published") is True
        and isinstance(item.get("week"), str)
    ]
    result["published_weeks"] = len(published)
    if published:
        menu = account.menu(published[0]["week"])
        recipes = menu.get("recipes") if isinstance(menu, dict) else None
        result["menu_checked"] = True
        result["recipes"] = len(recipes) if isinstance(recipes, list) else 0

    print(json.dumps(result, sort_keys=True))
    return 0 if result["weeks"] > 0 and (not published or result["recipes"] > 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
