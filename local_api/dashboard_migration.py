#!/usr/bin/env python3
"""Idempotent storage migration for the iPad family dashboard."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from family_config import child_profiles

DEFAULT_WORKSPACE = Path(
    os.environ.get("FAMILYBOT_WORKSPACE", str(Path.home() / ".openclaw/workspace"))
).expanduser()
DEFAULT_DB = DEFAULT_WORKSPACE / "db/family.db"
DEFAULT_BACKUPS = DEFAULT_WORKSPACE / "backups"
CORE_COMPONENT = "core"
SUPPORTED_CORE_SCHEMA_VERSION = 1
PORTAL_COMPONENT = "portal"
PORTAL_SCHEMA_VERSION = 2

MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS familybot_schema_migrations (
    component TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    PRIMARY KEY(component, version)
)
"""

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

PORTAL_REQUIRED_COLUMNS = {
    "family_chore_meta": {
        "card_id",
        "icon",
        "points",
        "requires_approval",
        "visible_to_kids",
        "repeat_mode",
        "repeat_weekdays",
        "repeat_target",
    },
    "chore_completions": {
        "id",
        "card_id",
        "member_id",
        "status",
        "points",
        "cycle_id",
        "occurrence_date",
    },
    "chore_cycles": {"id", "card_id", "member_id", "cycle_key", "status"},
    "reward_goals": {"id", "member_id", "title", "target_value", "active"},
    "weekly_achievement_cycles": {"id", "member_id", "target_points", "started_at", "ended_at"},
}


class PortalMigrationError(RuntimeError):
    """Raised when the Portal schema cannot be changed safely."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]
    fingerprint: str

    @property
    def checksum(self) -> str:
        value = f"{PORTAL_COMPONENT}:{self.version}:{self.name}:{self.fingerprint}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

DEFAULT_CHORES = [
    ("Gjøre lekser", "📖", 10, 0),
    ("Rydde rommet", "🧹", 5, 1),
    ("Tømme oppvaskmaskinen", "🍽️", 2, 0),
]


def _execute_script_transactionally(connection: sqlite3.Connection, script: str) -> None:
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            if statement.strip():
                connection.execute(statement)
            statement = ""
    if statement.strip():
        raise PortalMigrationError("Portal schema contains an incomplete SQL statement")


def _migration_001_portal_baseline(connection: sqlite3.Connection) -> None:
    _execute_script_transactionally(connection, SCHEMA)


RECURRENCE_COLUMNS = (
    ("family_chore_meta", "repeat_mode", "TEXT NOT NULL DEFAULT 'once'"),
    ("family_chore_meta", "repeat_weekdays", "TEXT NOT NULL DEFAULT ''"),
    ("family_chore_meta", "repeat_target", "INTEGER NOT NULL DEFAULT 1"),
    ("chore_completions", "cycle_id", "INTEGER REFERENCES chore_cycles(id)"),
    ("chore_completions", "occurrence_date", "TEXT"),
)


def _migration_002_recurring_chores(connection: sqlite3.Connection) -> None:
    for table, column, definition in RECURRENCE_COLUMNS:
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        if column not in columns:
            connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_chore_completions_cycle_date "
        "ON chore_completions(card_id, member_id, cycle_id, occurrence_date)"
    )


PORTAL_MIGRATIONS = (
    Migration(1, "portal-baseline", _migration_001_portal_baseline, SCHEMA),
    Migration(
        2,
        "recurring-chores",
        _migration_002_recurring_chores,
        repr(RECURRENCE_COLUMNS) + "|idx_chore_completions_cycle_date",
    ),
)


def _schema_version(connection: sqlite3.Connection, component: str) -> int:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='familybot_schema_migrations'"
    ).fetchone()
    if not exists:
        return 0
    row = connection.execute(
        "SELECT MAX(version) FROM familybot_schema_migrations WHERE component=?", (component,)
    ).fetchone()
    return int(row[0] or 0)


def verify_core_compatibility(connection: sqlite3.Connection) -> None:
    version = _schema_version(connection, CORE_COMPONENT)
    if version != SUPPORTED_CORE_SCHEMA_VERSION:
        raise PortalMigrationError(
            f"Core schema version {version} is incompatible; expected "
            f"{SUPPORTED_CORE_SCHEMA_VERSION}. Run the matching Core migration first."
        )
    for table in ("family_members", "kanban_cards", "week_plans", "week_plan_interpretations"):
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            raise PortalMigrationError(f"Required Core table is missing: {table}")


def validate_portal_schema(connection: sqlite3.Connection) -> None:
    for table, expected in PORTAL_REQUIRED_COLUMNS.items():
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        missing = sorted(expected - columns)
        if missing:
            raise PortalMigrationError(
                f"Portal table {table} is missing column(s): {', '.join(missing)}"
            )
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        raise PortalMigrationError("Portal schema has foreign-key violations")


def migration_status(db_path: Path) -> dict[str, int | bool]:
    if not db_path.is_file():
        return {"exists": False, "core": 0, "portal": 0, "current": False}
    with sqlite3.connect(db_path) as connection:
        core = _schema_version(connection, CORE_COMPONENT)
        portal = _schema_version(connection, PORTAL_COMPONENT)
        integrity = connection.execute("PRAGMA quick_check").fetchone()
    return {
        "exists": True,
        "core": core,
        "portal": portal,
        "current": core == SUPPORTED_CORE_SCHEMA_VERSION
        and portal == PORTAL_SCHEMA_VERSION
        and bool(integrity and integrity[0] == "ok"),
    }


def backup_database(db_path: Path, backup_root: Path) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_root.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_root, 0o700)
    target_dir = backup_root / f"dashboard-service-{stamp}"
    target_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(target_dir, 0o700)
    target = target_dir / "family.db"
    fd, temporary = tempfile.mkstemp(prefix=".family-", suffix=".db", dir=target_dir)
    os.close(fd)
    temporary_path = Path(temporary)
    source = sqlite3.connect(db_path)
    destination = sqlite3.connect(temporary_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    os.chmod(temporary_path, 0o600)
    with sqlite3.connect(temporary_path) as verification:
        integrity = verification.execute("PRAGMA integrity_check").fetchone()
    if not integrity or integrity[0] != "ok":
        temporary_path.unlink(missing_ok=True)
        raise PortalMigrationError("Portal backup failed its SQLite integrity check")
    os.replace(temporary_path, target)
    os.chmod(target, 0o600)
    return target


def migrate(db_path: Path, seed: bool = False) -> dict[str, int]:
    created_chores = 0
    created_rewards = 0
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        verify_core_compatibility(connection)
        existing_rows = connection.execute(
            """SELECT version,name,checksum FROM familybot_schema_migrations
               WHERE component=? ORDER BY version""",
            (PORTAL_COMPONENT,),
        ).fetchall()
        existing = {int(row[0]): row for row in existing_rows}
        known = {migration.version: migration for migration in PORTAL_MIGRATIONS}
        unknown = sorted(set(existing) - set(known))
        if unknown:
            raise PortalMigrationError(f"Database has unsupported future Portal migration(s): {unknown}")
        for version, row in existing.items():
            migration = known[version]
            if row[1] != migration.name or row[2] != migration.checksum:
                raise PortalMigrationError(
                    f"Portal migration {version} does not match reviewed source"
                )
        for migration in PORTAL_MIGRATIONS:
            if migration.version in existing:
                continue
            connection.execute("BEGIN IMMEDIATE")
            try:
                migration.apply(connection)
                connection.execute(
                    """INSERT INTO familybot_schema_migrations
                       (component,version,name,checksum,applied_at) VALUES(?,?,?,?,?)""",
                    (
                        PORTAL_COMPONENT,
                        migration.version,
                        migration.name,
                        migration.checksum,
                        dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    ),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        validate_portal_schema(connection)
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
        validate_portal_schema(connection)
    return {"chores": created_chores, "rewards": created_rewards}


def ensure_default_rewards(db_path: Path) -> int:
    """Restore an active individual goal for configured children that lack one."""
    created = 0
    workspace = db_path.parent.parent
    with sqlite3.connect(db_path) as connection:
        for profile in child_profiles(workspace):
            child_name = str(profile.get("name") or "").strip()
            if not child_name:
                continue
            member = connection.execute(
                "SELECT id FROM family_members WHERE lower(name)=lower(?) AND role='child'",
                (child_name,),
            ).fetchone()
            if not member or connection.execute(
                "SELECT 1 FROM reward_goals WHERE member_id=? AND active=1", (member[0],)
            ).fetchone():
                continue
            reward = profile.get("default_reward") or {}
            connection.execute(
                """INSERT INTO reward_goals(member_id,title,emoji,goal_type,target_value,unit_label,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    member[0],
                    str(reward.get("title") or "Familiebelønning"),
                    str(reward.get("emoji") or "🎯"),
                    str(reward.get("goal_type") or "points"),
                    int(reward.get("target_value") or 30),
                    str(reward.get("unit_label") or "poeng"),
                    dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                ),
            )
            created += 1
    return created


def clear_active_setup(db_path: Path) -> dict[str, int]:
    """Hide and archive the current kid setup without deleting its history."""
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        verify_core_compatibility(connection)
        validate_portal_schema(connection)
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
    mode.add_argument("--status", action="store_true")
    parser.add_argument("--repair-default-rewards", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    if not args.db.is_file():
        raise SystemExit(f"Database not found: {args.db}")
    if args.status:
        status = migration_status(args.db)
        print(json.dumps(status, sort_keys=True))
        if not status["current"]:
            raise SystemExit(1)
        return
    backup = None if args.no_backup else backup_database(args.db, args.backup_root)
    try:
        result = migrate(args.db, seed=args.seed)
        repaired_rewards = ensure_default_rewards(args.db) if args.repair_default_rewards else 0
        cleared = clear_active_setup(args.db) if args.clear_active_setup else None
    except (PortalMigrationError, sqlite3.Error, ValueError) as exc:
        raise SystemExit(
            f"Portal migration failed safely; restore from the reported backup if needed: {type(exc).__name__}"
        ) from exc
    if backup:
        print(f"[backup] {backup}")
    print(f"[migration] chores={result['chores']} rewards={result['rewards']}")
    if args.repair_default_rewards:
        print(f"[default-rewards] created={repaired_rewards}")
    if cleared:
        print(
            "[cleared] "
            f"archived_chores={cleared['archived_chores']} "
            f"deactivated_rewards={cleared['deactivated_rewards']}"
        )


if __name__ == "__main__":
    main()
