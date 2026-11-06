#!/usr/bin/env python3
"""Warm the bounded local cache for upcoming HelloFresh recipe images."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "local_api"))

from family_config import portal_settings  # noqa: E402
from hellofresh_account import HelloFreshAccountClient  # noqa: E402
from hellofresh_images import HelloFreshImageCache, prefetch_upcoming_images  # noqa: E402


def main() -> int:
    workspace = Path(os.environ.get("FAMILYBOT_WORKSPACE") or os.environ.get("OPENCLAW_WORKSPACE")
                     or str(Path.home() / ".familybot")).expanduser()
    try:
        features = portal_settings(workspace).get("features", {})
    except RuntimeError:
        print("[hellofresh-images] skipped: configuration unavailable", file=sys.stderr)
        return 1
    if not isinstance(features, dict) or not (
        features.get("hellofresh") is True and features.get("hellofresh_account") is True
    ):
        print("[hellofresh-images] skipped: account capability disabled")
        return 0
    # Re-read consent on every invocation, before creating a client or reading
    # retained tokens; stale scheduled jobs must also fail closed.
    account = HelloFreshAccountClient()
    if not account.status().get("connected"):
        print("[hellofresh-images] skipped: account is not connected")
        return 0
    try:
        result = prefetch_upcoming_images(account, HelloFreshImageCache())
    except Exception as exc:  # noqa: BLE001 - logs only the type, never provider details or credentials.
        print(f"[hellofresh-images] failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"[hellofresh-images] {json.dumps(result, sort_keys=True)}")
    return 0 if result["available"] > 0 or result["requested"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
