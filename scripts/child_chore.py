#!/usr/bin/env python3
"""Validated interview handoff for creating a child chore.

The conversational layer collects the fields, calls ``preview`` to show the
normalized result, and calls ``create`` only after the parent/agent receives an
explicit confirmation. The repository remains the only writer for chore data.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "local_api"))

from familybot_api import FamilyRepository, ValidationError, WEEKDAY_NAMES  # noqa: E402


def repository() -> FamilyRepository:
    workspace = Path(
        os.environ.get("FAMILYBOT_WORKSPACE", str(Path.home() / ".openclaw/workspace"))
    ).expanduser()
    database = Path(
        os.environ.get("FAMILYBOT_DB_PATH", str(workspace / "db/family.db"))
    ).expanduser()
    return FamilyRepository(database, workspace, workspace / "logs/familybot-portal-audit.jsonl")


def payload_from_args(args: argparse.Namespace) -> dict[str, object]:
    return {
        "assigned_to": args.child,
        "title": args.title,
        "description": args.description,
        "icon": args.icon,
        "points": args.points,
        "requires_approval": args.approval,
        "repeat_mode": args.repeat,
        "repeat_weekdays": args.weekdays,
    }


def summary(chore: dict[str, object]) -> str:
    repeat = "once"
    if chore["repeat_mode"] == "weekly":
        days = [WEEKDAY_NAMES[int(day)] for day in chore["repeat_weekdays"]]
        repeat = "weekly on " + ", ".join(days)
    approval = "parent approval required" if chore["requires_approval"] else "no approval required"
    return f'{chore["title"]} for {chore["assigned_to"]}: {chore["points"]} points, {repeat}, {approval}'


def emit(value: dict[str, object], status: int = 0) -> int:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Interview-safe child chore creation")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_fields(command: argparse.ArgumentParser) -> None:
        command.add_argument("--child", required=True, help="Configured child name")
        command.add_argument("--title", required=True)
        command.add_argument("--points", required=True, type=int)
        command.add_argument("--repeat", choices=("once", "weekly"), default="once")
        command.add_argument("--weekdays", default="", help="Comma-separated ISO weekdays 1-7")
        command.add_argument("--approval", action="store_true")
        command.add_argument("--icon", default="✨")
        command.add_argument("--description", default="")

    preview = sub.add_parser("preview", help="Normalize and display a proposed chore")
    add_fields(preview)

    create = sub.add_parser("create", help="Create a previously confirmed chore")
    add_fields(create)
    create.add_argument("--confirm", action="store_true", help="Required explicit confirmation")
    create.add_argument("--idempotency-key", required=True)

    args = parser.parse_args()
    try:
        repo = repository()
        chore = repo.normalize_child_chore(payload_from_args(args))
        if args.command == "preview":
            return emit({
                "ok": True,
                "mode": "interview",
                "confirmation_required": True,
                "chore": chore,
                "summary": summary(chore),
            })
        if not args.confirm:
            return emit({"ok": False, "error": "Explicit confirmation is required."}, 2)
        result = repo.create_child_chore(
            payload_from_args(args),
            idempotency_key=args.idempotency_key,
            source="telegram-interview",
        )
        duplicate = bool(result.pop("duplicate", False))
        return emit({
            "ok": True,
            "created": not duplicate,
            "duplicate": duplicate,
            "chore": result,
            "message": "Chore already existed for this confirmation." if duplicate else "Chore created.",
        })
    except (ValidationError, OSError, ValueError, KeyError) as exc:
        return emit({"ok": False, "error": str(exc)}, 2)


if __name__ == "__main__":
    raise SystemExit(main())
