#!/usr/bin/env python3
"""Idempotent storage migration for the iPad family dashboard."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sqlite3
from pathlib import Path

from family_config import child_profiles


DEFAULT_WORKSPACE = Path(
    os.environ.get("FAMILYBOT_WORKSPACE", str(Path.home() / ".openclaw/workspace"))
).expanduser()
DEFAULT_DB = DEFAULT_WORKSPACE / "db/family.db"
DEFAULT_BACKUPS = DEFAULT_WORKSPACE / "backups"

SCHEMA = """
CREATE TABLE IF NOT EXISTS family_chore_meta (
    card_id INTEGER PRIMARY KEY REFERENCES kanban_cards(id) ON DELETE CASCADE,
    icon TEXT NOT NULL DEFAULT '✨',
    points INTEGER NOT NULL DEFAULT 1 CHECK(points >= 0 AND points <= 1000),
    requires_approval INTEGER NOT NULL DEFAULT 0 CHECK(requires_approval IN (0,1)),
    visible_to_kids INTEGER NOT NULL DEFAULT 1 CHECK(visible_to_kids IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS child_chore_operations (
    id INTEGER PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    result_json TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'dashboard',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chore_completions (
    id INTEGER PRIMARY KEY,
    card_id INTEGER NOT NULL REFERENCES kanban_cards(id),
    member_id INTEGER NOT NULL REFERENCES family_members(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('pending','awarded','rejected')),
    points INTEGER NOT NULL CHECK(points >= 0 AND points <= 1000),
    completed_at TEXT NOT NULL,
    approved_by INTEGER REFERENCES family_members(id),
    decided_at TEXT,
    source TEXT NOT NULL DEFAULT 'dashboard'
);
CREATE INDEX IF NOT EXISTS idx_chore_completions_member_time
    ON chore_completions(member_id, completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_chore_completions_status
    ON chore_completions(status, completed_at);

CREATE TABLE IF NOT EXISTS chore_cycles (
    id INTEGER PRIMARY KEY,
    card_id INTEGER NOT NULL REFERENCES kanban_cards(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES family_members(id),
    cycle_key TEXT NOT NULL,
    required_count INTEGER NOT NULL CHECK(required_count >= 1 AND required_count <= 31),
    completed_count INTEGER NOT NULL DEFAULT 0 CHECK(completed_count >= 0 AND completed_count <= 31),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','pending','awarded','rejected','reset')),
    points INTEGER NOT NULL CHECK(points >= 0 AND points <= 1000),
    created_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE(card_id, member_id, cycle_key)
);
CREATE INDEX IF NOT EXISTS idx_chore_cycles_member_status
    ON chore_cycles(member_id, status, cycle_key);

CREATE TABLE IF NOT EXISTS reward_goals (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES family_members(id),
    title TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '🎯',
    goal_type TEXT NOT NULL DEFAULT 'points' CHECK(goal_type IN ('points','currency','items')),
    target_value INTEGER NOT NULL CHECK(target_value > 0 AND target_value <= 1000000),
    unit_label TEXT NOT NULL DEFAULT 'poeng',
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL,
    achieved_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_reward_goals_one_active
    ON reward_goals(member_id) WHERE active=1;

CREATE TABLE IF NOT EXISTS weekly_achievement_cycles (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES family_members(id),
    target_points INTEGER NOT NULL DEFAULT 30 CHECK(target_points > 0 AND target_points <= 1000),
    started_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_weekly_achievement_one_active
    ON weekly_achievement_cycles(member_id) WHERE ended_at IS NULL;

CREATE TABLE IF NOT EXISTS weekly_surprise_levels (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES family_members(id),
    threshold_weeks INTEGER NOT NULL CHECK(threshold_weeks > 0 AND threshold_weeks <= 10000),
    title TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '🎁',
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(member_id, threshold_weeks)
);

CREATE TABLE IF NOT EXISTS weekly_achievement_redemptions (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES family_members(id),
    cycle_id INTEGER NOT NULL REFERENCES weekly_achievement_cycles(id),
    full_weeks INTEGER NOT NULL CHECK(full_weeks >= 0),
    threshold_weeks INTEGER,
    title TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_weekly_achievement_redemptions_member
    ON weekly_achievement_redemptions(member_id, created_at DESC);

CREATE TABLE IF NOT EXISTS weekly_achievement_reset_operations (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES family_members(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dashboard_reset_operations (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES family_members(id),
    scope TEXT NOT NULL CHECK(scope IN ('chores','points','both')),
    idempotency_key TEXT NOT NULL UNIQUE,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

DEFAULT_CHORES = [
    ("Gjøre lekser", "📖", 10, 0),
    ("Rydde rommet", "🧹", 5, 1),
    ("Tømme oppvaskmaskinen", "🍽️", 2, 0),
]


def backup_database(db_path: Path, backup_root: Path) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target_dir = backup_root / f"dashboard-service-{stamp}"
    target_dir.mkdir(parents=True, exist_ok=False)
    target = target_dir / "family.db"
    source = sqlite3.connect(db_path)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return target


def migrate(db_path: Path, seed: bool = False) -> dict[str, int]:
    created_chores = 0
    created_rewards = 0
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(SCHEMA)
        for table, column, definition in (
            ("family_chore_meta", "repeat_mode", "TEXT NOT NULL DEFAULT 'once'"),
            ("family_chore_meta", "repeat_weekdays", "TEXT NOT NULL DEFAULT ''"),
            ("family_chore_meta", "repeat_target", "INTEGER NOT NULL DEFAULT 1"),
            ("chore_completions", "cycle_id", "INTEGER REFERENCES chore_cycles(id)"),
            ("chore_completions", "occurrence_date", "TEXT"),
        ):
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_chore_completions_cycle_date "
            "ON chore_completions(card_id, member_id, cycle_id, occurrence_date)"
        )
        if seed:
            workspace = db_path.parent.parent
            for profile in child_profiles(workspace):
                child_name = str(profile.get("name") or "").strip()
                if not child_name:
                    continue
                member = connection.execute(
                    "SELECT id,name FROM family_members WHERE lower(name)=lower(?) AND role='child'",
                    (child_name,),
                ).fetchone()
                if not member:
                    continue
                for title, icon, points, approval in DEFAULT_CHORES:
                    exists = connection.execute(
                        """SELECT 1 FROM kanban_cards k JOIN family_chore_meta m ON m.card_id=k.id
                           WHERE lower(k.assigned_to)=lower(?) AND lower(k.title)=lower(?)
                             AND k.archived_at IS NULL""",
                        (child_name, title),
                    ).fetchone()
                    if exists:
                        continue
                    cursor = connection.execute(
                        """INSERT INTO kanban_cards(title,description,assigned_to,lane,priority)
                           VALUES(?,NULL,?,'todo','nice-to')""",
                        (title, child_name.lower()),
                    )
                    connection.execute(
                        """INSERT INTO family_chore_meta(card_id,icon,points,requires_approval)
                           VALUES(?,?,?,?)""",
                        (cursor.lastrowid, icon, points, approval),
                    )
                    created_chores += 1
                has_goal = connection.execute(
                    "SELECT 1 FROM reward_goals WHERE member_id=? AND active=1", (member[0],)
                ).fetchone()
                if not has_goal:
                    reward = profile.get("default_reward") or {}
                    title = str(reward.get("title") or "Familiebelønning")
                    emoji = str(reward.get("emoji") or "🎯")
                    target = int(reward.get("target_value") or 30)
                    goal_type = str(reward.get("goal_type") or "points")
                    unit = str(reward.get("unit_label") or "poeng")
                    connection.execute(
                        """INSERT INTO reward_goals(member_id,title,emoji,goal_type,target_value,unit_label,created_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        (member[0], title, emoji, goal_type, target, unit, dt.datetime.now().astimezone().isoformat(timespec="seconds")),
                    )
                    created_rewards += 1
        now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        for member_id, in connection.execute("SELECT id FROM family_members WHERE role='child'"):
            connection.execute(
                """INSERT INTO weekly_achievement_cycles(member_id,target_points,started_at)
                   SELECT ?,30,? WHERE NOT EXISTS (
                       SELECT 1 FROM weekly_achievement_cycles WHERE member_id=? AND ended_at IS NULL
                   )""",
                (member_id, now, member_id),
            )
    return {"chores": created_chores, "rewards": created_rewards}


def clear_active_setup(db_path: Path) -> dict[str, int]:
    """Hide and archive the current kid setup without deleting its history."""
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(SCHEMA)
        active_chores = connection.execute(
            """SELECT COUNT(*) FROM kanban_cards k
               JOIN family_chore_meta m ON m.card_id=k.id
               WHERE k.archived_at IS NULL AND m.visible_to_kids=1"""
        ).fetchone()[0]
        active_rewards = connection.execute(
            "SELECT COUNT(*) FROM reward_goals WHERE active=1"
        ).fetchone()[0]
        connection.execute(
            """UPDATE kanban_cards SET archived_at=?,updated_at=?
               WHERE archived_at IS NULL AND id IN (
                   SELECT card_id FROM family_chore_meta WHERE visible_to_kids=1
               )""",
            (now, now),
        )
        connection.execute(
            "UPDATE family_chore_meta SET visible_to_kids=0,updated_at=? WHERE visible_to_kids=1",
            (now,),
        )
        connection.execute("UPDATE reward_goals SET active=0 WHERE active=1")
    return {"archived_chores": int(active_chores), "deactivated_rewards": int(active_rewards)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUPS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--seed", action="store_true")
    mode.add_argument("--clear-active-setup", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    if not args.db.is_file():
        raise SystemExit(f"Database not found: {args.db}")
    backup = None if args.no_backup else backup_database(args.db, args.backup_root)
    result = migrate(args.db, seed=args.seed)
    cleared = clear_active_setup(args.db) if args.clear_active_setup else None
    if backup:
        print(f"[backup] {backup}")
    print(f"[migration] chores={result['chores']} rewards={result['rewards']}")
    if cleared:
        print(
            "[cleared] "
            f"archived_chores={cleared['archived_chores']} "
            f"deactivated_rewards={cleared['deactivated_rewards']}"
        )


if __name__ == "__main__":
    main()
