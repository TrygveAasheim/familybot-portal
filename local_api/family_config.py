#!/usr/bin/env python3
"""Load household identity from an ignored, owner-readable local file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def config_path(workspace: Path) -> Path:
    configured = os.environ.get("FAMILYBOT_FAMILY_CONFIG")
    return Path(configured).expanduser() if configured else workspace / "config/family.local.json"


def load_family_config(workspace: Path) -> dict[str, Any]:
    path = config_path(workspace)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Local family configuration is missing or invalid: {path}. "
            "Copy the canonical familybot-core/config/family.example.json and fill it locally."
        ) from exc
    if not isinstance(value, dict) or not isinstance(value.get("members"), list):
        raise RuntimeError(f"Local family configuration has no members list: {path}")
    return value


def member_profiles(workspace: Path) -> dict[int, dict[str, Any]]:
    profiles: dict[int, dict[str, Any]] = {}
    for member in load_family_config(workspace)["members"]:
        if not isinstance(member, dict):
            continue
        try:
            member_id = int(member["member_id"])
        except (KeyError, TypeError, ValueError):
            continue
        profiles[member_id] = member
    return profiles


def child_profiles(workspace: Path) -> list[dict[str, Any]]:
    return [
        profile for profile in member_profiles(workspace).values()
        if profile.get("role") == "child"
    ]


def integration(workspace: Path, name: str) -> dict[str, Any]:
    value = load_family_config(workspace).get("integrations", {}).get(name, {})
    return value if isinstance(value, dict) else {}


def portal_settings(workspace: Path) -> dict[str, Any]:
    value = load_family_config(workspace).get("portal", {})
    return value if isinstance(value, dict) else {}
