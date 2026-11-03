#!/usr/bin/env python3
"""Warm the bounded local cache for upcoming HelloFresh recipe images."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "local_api"))

from hellofresh_account import HelloFreshAccountClient  # noqa: E402
from hellofresh_images import HelloFreshImageCache, prefetch_upcoming_images  # noqa: E402


def main() -> int:
    account = HelloFreshAccountClient()
    if not account.status().get("connected"):
        print("[hellofresh-images] skipped: account is not connected")
        return 0
    try:
        result = prefetch_upcoming_images(account, HelloFreshImageCache())
    except Exception as exc:  # Provider details and credentials must never enter this log.
        print(f"[hellofresh-images] failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"[hellofresh-images] {json.dumps(result, sort_keys=True)}")
    return 0 if result["available"] > 0 or result["requested"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
