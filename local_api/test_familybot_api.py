import datetime as dt
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard_migration import clear_active_setup, ensure_default_rewards, migrate
from familybot_api import FamilyApiServer, FamilyRepository, ValidationError, health_summary, transport_summary, trusted_portal_origin, weather_summary


SCHEMA = """
CREATE TABLE family_members(id INTEGER PRIMARY KEY,name TEXT,role TEXT,grade INTEGER,school TEXT,teacher TEXT,telegram_id TEXT,notes TEXT,created_at TEXT);
CREATE TABLE calendar_events(id INTEGER PRIMARY KEY,member_id INTEGER,title TEXT,event_date TEXT,event_time TEXT,end_date TEXT,location TEXT,description TEXT,bring TEXT,requires_response INTEGER,response_deadline TEXT,source TEXT,source_ref TEXT,week_number INTEGER,year INTEGER,created_at TEXT);
CREATE TABLE spond_events(id TEXT PRIMARY KEY,group_id TEXT,group_name TEXT,member_id INTEGER,title TEXT,event_date TEXT,event_end TEXT,location TEXT,description TEXT,rsvp_accepted INTEGER,rsvp_declined INTEGER,rsvp_unanswered INTEGER,my_rsvp TEXT,rsvp_deadline TEXT,requires_response INTEGER,raw_json TEXT,first_seen TEXT,last_updated TEXT,notified INTEGER);
CREATE TABLE activities(id INTEGER PRIMARY KEY,member_id INTEGER,name TEXT,description TEXT,location TEXT,schedule TEXT,spond_group_id TEXT,active INTEGER,notes TEXT,created_at TEXT,paused_until TEXT);
CREATE TABLE kanban_cards(id INTEGER PRIMARY KEY,title TEXT NOT NULL,description TEXT,assigned_to TEXT,lane TEXT DEFAULT 'todo',priority TEXT DEFAULT 'nice-to',due_date TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,archived_at TEXT);
CREATE TABLE week_plans(id INTEGER PRIMARY KEY,member_id INTEGER,week_number INTEGER,year INTEGER,raw_text TEXT,summary TEXT,source_email_id TEXT,teacher TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE week_plan_days(id INTEGER PRIMARY KEY,week_plan_id INTEGER,day TEXT NOT NULL,date TEXT,subject TEXT,note TEXT,homework TEXT,bring TEXT);
CREATE TABLE email_log(id INTEGER PRIMARY KEY,message_id TEXT,subject TEXT,sender TEXT,received_at TEXT,processed_at TEXT,member_id INTEGER,category TEXT,has_pdf INTEGER,summary TEXT);
CREATE TABLE school_calendar(id INTEGER PRIMARY KEY,year_label TEXT,event_type TEXT,name TEXT,start_date TEXT,end_date TEXT,applies_to TEXT,notes TEXT);
"""


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = root / "db/family.db"
        self.db.parent.mkdir(parents=True)
        (root / "config").mkdir()
        (root / "config/family.local.json").write_text(json.dumps({"members": [
            {"member_id": 1, "role": "parent", "name": "Parent One", "slug": "parent_1"},
            {"member_id": 3, "role": "child", "name": "Child One", "slug": "child_1", "avatar": "🧑‍🚀", "grade": 3,
             "default_reward": {"title": "Card pack", "emoji": "🃏", "target_value": 30}},
            {"member_id": 4, "role": "child", "name": "Child Two", "slug": "child_2", "avatar": "🦋", "grade": 6,
             "default_reward": {"title": "Cinema", "emoji": "🎬", "target_value": 30}},
        ], "integrations": {
            "transport": {
                "transport_mode": "metro", "stop_name": "Local Station", "stop_id": "NSR:StopPlace:test",
                "direction_quay_id": "NSR:Quay:test", "line": "2",
                "direction_label": "Next toward centre", "client_name": "familybot-test",
            },
            "weather": {
                "home_lat": 1.25, "home_lon": 2.5,
                "user_agent": "FamilyBot-test/1.0 contact@example.invalid",
            },
        }}), encoding="utf-8")
        with sqlite3.connect(self.db) as connection:
            connection.executescript(SCHEMA)
            connection.executemany("INSERT INTO family_members(id,name,role,grade) VALUES(?,?,?,?)", [(1,"Parent One","parent",None),(3,"Child One","child",3),(4,"Child Two","child",6)])
            connection.execute("INSERT INTO email_log VALUES(1,'m1','Ukeplan og informasjon','school@example.no','2026-08-13','2026-08-13',NULL,'school',1,'Velkommen til 3A. Hemmelig råtekst')")
            connection.execute("INSERT INTO school_calendar VALUES(1,'2026-2027','first_day','Første skoledag','2026-08-17','2026-08-17','oslo',NULL)")
        migrate(self.db)
        (root / "db/health_failures.json").write_text('{"database":0}', encoding="utf-8")
        (root / "db/dashboard_weather.json").write_text(json.dumps({
            "status": "16 °C · delvis skyet",
            "forecast_version": 3,
            "advice": "En lett jakke kan være nyttig tidlig og sent.",
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source": "MET Locationforecast", "stale": False,
        }), encoding="utf-8")
        (root / "db/dashboard_departures.json").write_text(json.dumps({
            "ok": True, "status": "Next toward centre", "stop": "Local Station",
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source": "Entur Journey Planner", "stale": False,
            "departures": [{
                "expected_departure": "2026-08-16T10:37:00+02:00",
                "aimed_departure": "2026-08-16T10:37:00+02:00",
                "destination": "City Terminus", "line": "2", "platform": "1", "realtime": True,
            }],
        }), encoding="utf-8")
        self.repo = FamilyRepository(self.db, root, root / "audit.jsonl")

    def tearDown(self):
        self.temp.cleanup()

    def test_dashboard_is_curated_and_detects_unlinked_week_plan(self):
        dashboard = self.repo.dashboard(dt.date(2026, 8, 15))
        encoded = json.dumps(dashboard, ensure_ascii=False)
        self.assertNotIn("Hemmelig råtekst", encoded)
        self.assertNotIn("school@example.no", encoded)
        self.assertEqual(dashboard["target_week"]["week"], 34)
        self.assertEqual(dashboard["unlinked_week_plan_messages"][0]["candidate_member"], "Child One")
        child_one = next(item for item in dashboard["week_plan_status"] if item["member"] == "Child One")
        self.assertTrue(child_one["inbox_candidate"])
        self.assertFalse(child_one["received"])

    def test_dashboard_separates_parent_kanban_from_child_chores(self):
        child_chore = self.repo.create_child_chore({
            "title": "Les lekse", "assigned_to": "child one", "icon": "📖", "points": 2,
        })
        parent_task = self.repo.create_chore({
            "title": "Bestill billetter", "assigned_to": "both", "priority": "important",
        })
        dashboard = self.repo.dashboard(dt.date(2026, 8, 15))
        kanban_ids = {item["id"] for item in dashboard["chores"]}
        child = next(item for item in dashboard["children"] if item["name"] == "Child One")
        self.assertIn(parent_task["id"], kanban_ids)
        self.assertNotIn(child_chore["id"], kanban_ids)
        self.assertIn(child_chore["id"], {item["id"] for item in child["chores"]})

    def test_interview_child_chore_is_normalized_and_idempotent(self):
        payload = {
            "title": "Lekser på hverdager", "assigned_to": "child one", "icon": "📖",
            "points": 4, "requires_approval": True, "repeat_mode": "weekly",
            "repeat_weekdays": "1,2,3,4,5",
        }
        preview = self.repo.normalize_child_chore(payload)
        self.assertEqual(preview["repeat_weekdays"], [1, 2, 3, 4, 5])
        first = self.repo.create_child_chore(payload, idempotency_key="telegram-interview-001", source="telegram-interview")
        duplicate = self.repo.create_child_chore({**payload, "title": "Should not duplicate"}, idempotency_key="telegram-interview-001", source="telegram-interview")
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(first["id"], duplicate["id"])
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM child_chore_operations").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM family_chore_meta").fetchone()[0], 1)

    def test_health_status_only_stops_for_core_failure(self):
        root = Path(self.temp.name)
        status_path = root / "db/health_status.json"
        status_path.write_text(json.dumps({
            "checked_at": "2026-08-17T18:00:00+02:00",
            "results": [{"service": "telegram", "status": "warn", "msg": "unavailable"}],
        }), encoding="utf-8")
        degraded = health_summary(root)
        self.assertEqual(degraded["status"], "degraded")
        self.assertTrue(degraded["ok"])
        self.assertEqual(degraded["issues"][0]["label"], "meldingskanal")

        status_path.write_text(json.dumps({
            "checked_at": "2026-08-17T18:01:00+02:00",
            "results": [{"service": "gateway", "status": "critical", "msg": "down"}],
        }), encoding="utf-8")
        stopped = health_summary(root)
        self.assertEqual(stopped["status"], "stopped")
        self.assertFalse(stopped["ok"])

        status_path.write_text(json.dumps({
            "checked_at": "2026-08-17T18:02:00+02:00",
            "results": [{"service": "gateway", "status": "ok", "msg": "running"}],
        }), encoding="utf-8")
        self.assertEqual(health_summary(root)["status"], "ok")

    def test_chore_create_move_archive_and_restore(self):
        chore = self.repo.create_chore({"title":"Pakke gymtøy","assigned_to":"child one","priority":"important","due_date":"2026-08-18"})
        self.assertEqual(chore["lane"], "todo")
        moved = self.repo.update_chore(chore["id"], {"lane":"done"})
        self.assertEqual(moved["lane"], "done")
        paused = self.repo.update_chore(chore["id"], {"lane":"onhold"})
        self.assertEqual(paused["lane"], "onhold")
        archived = self.repo.archive_chore(chore["id"])
        self.assertIsNotNone(archived["archived_at"])
        restored = self.repo.restore_chore(chore["id"])
        self.assertIsNone(restored["archived_at"])
        self.assertTrue(any((Path(self.temp.name) / "backups").glob("portal-chores-*/family.db")))
        self.assertIn("chore.restored", self.repo.audit_path.read_text(encoding="utf-8"))

    def test_rejects_invalid_chore_values(self):
        with self.assertRaises(ValidationError):
            self.repo.create_chore({"title":"", "assigned_to":"child one", "priority":"nice-to"})
        with self.assertRaises(ValidationError):
            self.repo.create_chore({"title":"Test", "assigned_to":"unknown", "priority":"nice-to"})

    def test_child_completion_is_durable_idempotent_and_awarded(self):
        chore = self.repo.create_child_chore({
            "title": "Pakke gymtøy", "assigned_to": "child one", "icon": "🎒", "points": 7,
        })
        first = self.repo.complete_chore(chore["id"], {"member_id": 3, "idempotency_key": "test-key-123"})
        duplicate = self.repo.complete_chore(chore["id"], {"member_id": 3, "idempotency_key": "test-key-123"})
        self.assertEqual(first["status"], "awarded")
        self.assertTrue(duplicate["duplicate"])
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM chore_completions").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT lane FROM kanban_cards WHERE id=?", (chore["id"],)).fetchone()[0], "done")

    def test_parent_approval_awards_once_and_rejection_reopens(self):
        chore = self.repo.create_child_chore({
            "title": "Rydde rommet", "assigned_to": "child two", "icon": "🧹", "points": 5,
            "requires_approval": True,
        })
        pending = self.repo.complete_chore(chore["id"], {"member_id": 4, "idempotency_key": "approval-key-123"})
        self.assertEqual(pending["status"], "pending")
        awarded = self.repo.decide_completion(pending["id"], {"decision": "awarded"}, 1)
        unchanged = self.repo.decide_completion(pending["id"], {"decision": "awarded"}, 1)
        self.assertEqual(awarded["status"], "awarded")
        self.assertTrue(unchanged["unchanged"])

        ordinary = self.repo.create_child_chore({
            "title": "Tømme sekk", "assigned_to": "child one", "icon": "🎒", "points": 3,
        })
        completed = self.repo.complete_chore(ordinary["id"], {"member_id": 3, "idempotency_key": "ordinary-key-123"})
        rejected = self.repo.decide_completion(completed["id"], {"decision": "rejected"}, 1)
        self.assertEqual(rejected["status"], "rejected")
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT lane FROM kanban_cards WHERE id=?", (ordinary["id"],)).fetchone()[0], "todo")

    def test_reward_progress_and_curated_child_contract(self):
        self.repo.set_reward({"member_id": 3, "title": "Kinokveld", "emoji": "🎬", "target_value": 10})
        chore = self.repo.create_child_chore({"title": "Lekser", "assigned_to": "child one", "icon": "📖", "points": 4})
        self.repo.complete_chore(chore["id"], {"member_id": 3, "idempotency_key": "reward-key-123"})
        dashboard = self.repo.dashboard(dt.date(2026, 8, 15))
        child_one = next(item for item in dashboard["children"] if item["name"] == "Child One")
        self.assertEqual(child_one["reward"]["earned"], 4)
        self.assertEqual(child_one["reward"]["remaining"], 6)
        self.assertNotIn("telegram_id", json.dumps(dashboard))

    def test_pending_points_move_progress_immediately(self):
        self.repo.set_reward({"member_id": 4, "title": "Kino", "emoji": "🎬", "target_value": 10})
        chore = self.repo.create_child_chore({
            "title": "Rydde", "assigned_to": "child two", "icon": "🧹", "points": 5,
            "requires_approval": True,
        })
        completion = self.repo.complete_chore(chore["id"], {"member_id": 4, "idempotency_key": "pending-progress-123"})
        self.assertEqual(completion["status"], "pending")
        dashboard = self.repo.dashboard(dt.date(2026, 8, 15))
        child_two = next(item for item in dashboard["children"] if item["name"] == "Child Two")
        self.assertEqual(child_two["reward"]["earned"], 5)
        self.assertEqual(child_two["reward"]["percent"], 50)

    def test_weekly_chore_requires_all_selected_days_before_approval(self):
        chore = self.repo.create_child_chore({
            "title": "Lekser hver ukedag", "assigned_to": "child one", "icon": "📖", "points": 10,
            "requires_approval": True, "repeat_mode": "weekly", "repeat_weekdays": [1, 2, 3, 4, 5],
        })
        weekdays = [dt.date(2026, 8, day) for day in range(17, 22)]
        with patch("familybot_api.dt.date") as date_class:
            date_class.today.side_effect = weekdays + [weekdays[-1]]
            for index in range(5):
                result = self.repo.complete_chore(
                    chore["id"], {"member_id": 3, "idempotency_key": f"weekday-key-{index:02d}"}
                )
                self.assertEqual(result["repeat_completed"], index + 1)
                self.assertEqual(result["points"], 10)
            with self.assertRaises(ValidationError):
                self.repo.complete_chore(
                    chore["id"], {"member_id": 3, "idempotency_key": "weekday-duplicate"}
                )
        dashboard = self.repo.dashboard(weekdays[-1])
        child = next(item for item in dashboard["children"] if item["id"] == 3)
        self.assertEqual(child["chores"][0]["repeat_completed"], 5)
        self.assertEqual(child["chores"][0]["repeat_percent"], 100)
        self.assertEqual(len(dashboard["approval_queue"]), 5)
        awarded = self.repo.decide_completion(
            dashboard["approval_queue"][0]["id"], {"decision": "awarded"}, 1
        )
        self.assertEqual(awarded["status"], "awarded")
        after_award = self.repo.dashboard(weekdays[-1])
        self.assertEqual(len(after_award["review_queue"]), 4)
        self.assertEqual(
            next(item for item in after_award["children"][0]["history"] if item["id"] == awarded["id"])["points"],
            10,
        )
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT SUM(points) FROM chore_completions").fetchone()[0], 50)
        next_week = self.repo.dashboard(dt.date(2026, 8, 24))
        next_child = next(item for item in next_week["children"] if item["id"] == 3)
        self.assertEqual(next_child["chores"][0]["repeat_completed"], 0)

    def test_weekly_chore_awards_once_without_approval(self):
        chore = self.repo.create_child_chore({
            "title": "Vask hendene", "assigned_to": "child two", "icon": "🧼", "points": 3,
            "repeat_mode": "weekly", "repeat_weekdays": [1, 2],
        })
        dates = [dt.date(2026, 8, 17), dt.date(2026, 8, 18)]
        with patch("familybot_api.dt.date") as date_class:
            date_class.today.side_effect = dates
            first = self.repo.complete_chore(chore["id"], {"member_id": 4, "idempotency_key": "wash-day-001"})
            second = self.repo.complete_chore(chore["id"], {"member_id": 4, "idempotency_key": "wash-day-002"})
        self.assertEqual(first["points"], 3)
        self.assertEqual(second["points"], 3)
        self.assertEqual(second["repeat_status"], "awarded")

    def test_repeated_points_are_visible_immediately_and_parent_can_reject_one_day(self):
        chore = self.repo.create_child_chore({
            "title": "Ta ut søppel", "assigned_to": "child two", "icon": "🗑️", "points": 3,
            "requires_approval": True, "repeat_mode": "weekly", "repeat_weekdays": [1, 2],
        })
        completion_date = dt.date(2026, 8, 17)
        with patch("familybot_api.dt.date") as date_class, \
                patch("familybot_api.iso_now", return_value="2026-08-17T12:00:00+02:00"):
            date_class.today.return_value = completion_date
            self.repo.set_reward({"member_id": 4, "title": "Kino", "emoji": "🎬", "target_value": 30})
            with sqlite3.connect(self.db) as connection:
                connection.execute(
                    "UPDATE weekly_achievement_cycles SET started_at=? WHERE member_id=? AND ended_at IS NULL",
                    ("2026-08-16T12:00:00+02:00", 4),
                )
            completion = self.repo.complete_chore(chore["id"], {"member_id": 4, "idempotency_key": "visible-repeat-points"})
        self.assertEqual(completion["points"], 3)
        dashboard = self.repo.dashboard(dt.date(2026, 8, 17))
        child = next(item for item in dashboard["children"] if item["id"] == 4)
        self.assertEqual(child["reward"]["earned"], 3)
        self.assertEqual(child["weekly_achievement"]["current_points"], 3)
        self.assertEqual(len(dashboard["approval_queue"]), 1)
        rejected = self.repo.decide_completion(completion["id"], {"decision": "rejected"}, 1)
        self.assertEqual(rejected["status"], "rejected")
        after = self.repo.dashboard(dt.date(2026, 8, 17))
        child = next(item for item in after["children"] if item["id"] == 4)
        self.assertEqual(child["reward"]["earned"], 0)
        self.assertEqual(child["weekly_achievement"]["current_points"], 0)

    def test_weekly_achievement_counts_full_week_and_preserves_redemption(self):
        self.repo.set_weekly_surprise(3, {"threshold_weeks": 1, "title": "Liten overraskelse", "emoji": "🎁"})
        self.repo.set_weekly_surprise(3, {"threshold_weeks": 2, "title": "Bedre overraskelse", "emoji": "🌟"})
        first = self.repo.create_child_chore({"title": "Lekser", "assigned_to": "child one", "icon": "📖", "points": 20})
        second = self.repo.create_child_chore({"title": "Rydde", "assigned_to": "child one", "icon": "🧹", "points": 15})
        self.repo.complete_chore(first["id"], {"member_id": 3, "idempotency_key": "achievement-20"})
        self.repo.complete_chore(second["id"], {"member_id": 3, "idempotency_key": "achievement-10"})
        today = dt.date.today()
        dashboard = self.repo.dashboard(today)
        child = next(item for item in dashboard["children"] if item["id"] == 3)
        achievement = child["weekly_achievement"]
        self.assertEqual(achievement["total_points"], 35)
        self.assertEqual(achievement["current_points"], 5)
        self.assertEqual(achievement["full_tabs"], 1)
        self.assertEqual(achievement["full_weeks"], 1)
        self.assertEqual(achievement["ready_surprises"][0]["title"], "Liten overraskelse")
        self.assertEqual(achievement["next_surprise"]["threshold_weeks"], 2)
        reset = self.repo.reset_weekly_achievement(3, {"threshold_weeks": 1, "idempotency_key": "achievement-reset-1"})
        duplicate = self.repo.reset_weekly_achievement(3, {"threshold_weeks": 1, "idempotency_key": "achievement-reset-1"})
        self.assertEqual(reset["previous_full_tabs"], 1)
        self.assertEqual(reset["previous_full_weeks"], 1)
        self.assertEqual(reset["claimed_surprise"]["title"], "Liten overraskelse")
        self.assertTrue(duplicate["duplicate"])
        after = next(item for item in self.repo.dashboard(today)["children"] if item["id"] == 3)["weekly_achievement"]
        self.assertEqual(after["full_weeks"], 0)
        self.assertEqual(after["redemptions"][0]["title"], "Liten overraskelse")

    def test_january_summary_counts_retained_child_completions(self):
        chore = self.repo.create_child_chore({
            "title": "Årsoppgave", "assigned_to": "child one", "icon": "✅", "points": 2,
        })
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                """INSERT INTO chore_completions(card_id,member_id,idempotency_key,status,points,completed_at)
                   VALUES(?,?,?,'awarded',?,?)""",
                (chore["id"], 3, "annual-summary-2025", 2, "2025-12-31T23:30:00+01:00"),
            )
        january = self.repo.dashboard(dt.date(2026, 1, 5))
        summary = january["annual_chore_summary"]
        self.assertEqual(summary["year"], 2025)
        self.assertEqual(next(item for item in summary["children"] if item["id"] == 3)["count"], 1)
        self.assertIsNone(self.repo.dashboard(dt.date(2026, 8, 15))["annual_chore_summary"])

    def test_blocks_carry_across_calendar_weeks(self):
        first = self.repo.create_child_chore({
            "title": "Mandagsoppgave", "assigned_to": "child one", "icon": "✅", "points": 20,
        })
        second = self.repo.create_child_chore({
            "title": "Neste ukesoppgave", "assigned_to": "child one", "icon": "⭐", "points": 15,
        })
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                "UPDATE weekly_achievement_cycles SET started_at=? WHERE member_id=? AND ended_at IS NULL",
                ("2026-08-01T00:00:00+02:00", 3),
            )
            connection.executemany(
                """INSERT INTO chore_completions(card_id,member_id,idempotency_key,status,points,completed_at)
                   VALUES(?,?,?,'awarded',?,?)""",
                [
                    (first["id"], 3, "cross-week-20", 20, "2026-08-17T12:00:00+02:00"),
                    (second["id"], 3, "cross-week-15", 15, "2026-08-24T12:00:00+02:00"),
                ],
            )
        achievement = next(
            item for item in self.repo.dashboard(dt.date(2026, 8, 24))["children"] if item["id"] == 3
        )["weekly_achievement"]
        self.assertEqual(achievement["total_points"], 35)
        self.assertEqual(achievement["full_tabs"], 1)
        self.assertEqual(achievement["current_points"], 5)

    def test_completed_block_restarts_active_progress_at_zero(self):
        chore = self.repo.create_child_chore({
            "title": "Full blokk", "assigned_to": "child one", "icon": "🏁", "points": 30,
        })
        self.repo.complete_chore(chore["id"], {"member_id": 3, "idempotency_key": "full-block-30"})
        achievement = next(
            item for item in self.repo.dashboard(dt.date(2026, 8, 24))["children"] if item["id"] == 3
        )["weekly_achievement"]
        self.assertEqual(achievement["full_tabs"], 1)
        self.assertEqual(achievement["current_points"], 0)
        self.assertEqual(achievement["current_percent"], 0)

    def test_parent_can_reset_child_chores_and_points_idempotently(self):
        self.repo.set_reward({"member_id": 3, "title": "Ny premie", "emoji": "🎯", "target_value": 20})
        chore = self.repo.create_child_chore({
            "title": "Ferdig rutine", "assigned_to": "child one", "icon": "✅", "points": 6,
        })
        self.repo.complete_chore(chore["id"], {"member_id": 3, "idempotency_key": "reset-complete-01"})
        result = self.repo.reset_child(3, {"scope": "both", "idempotency_key": "reset-child-001"})
        duplicate = self.repo.reset_child(3, {"scope": "both", "idempotency_key": "reset-child-001"})
        self.assertEqual(result["archived_chores"], 1)
        self.assertTrue(result["reset_points"])
        self.assertTrue(duplicate["duplicate"])
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM chore_completions").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reward_goals WHERE member_id=3 AND active=1").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reward_goals WHERE member_id=3").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT archived_at FROM kanban_cards WHERE id=?", (chore["id"],)).fetchone()[0] is not None, True)
        dashboard = self.repo.dashboard(dt.date(2026, 8, 15))
        child = next(item for item in dashboard["children"] if item["id"] == 3)
        self.assertEqual(child["chores"], [])
        self.assertEqual(child["reward"]["earned"], 0)

    def test_lan_origin_boundary(self):
        allowed = {"http://familie.local:3000", "http://localhost:3000"}
        self.assertTrue(trusted_portal_origin("http://familie.local:3000", allowed))
        self.assertFalse(trusted_portal_origin("http://192.168.1.20:3000", allowed))
        self.assertFalse(trusted_portal_origin("https://evil.example:3000"))
        self.assertFalse(trusted_portal_origin("http://8.8.8.8:3000"))
        self.assertFalse(trusted_portal_origin("http://localhost:9999"))
        self.assertFalse(trusted_portal_origin(None, allowed))

    def test_parent_pin_attempts_are_rate_limited(self):
        server = FamilyApiServer(("127.0.0.1", 0), self.repo, "123456")
        try:
            for _ in range(5):
                self.assertTrue(server.parent_login_allowed("192.168.1.20"))
                server.record_parent_login("192.168.1.20", succeeded=False)
            self.assertFalse(server.parent_login_allowed("192.168.1.20"))
            server.record_parent_login("192.168.1.20", succeeded=True)
            self.assertTrue(server.parent_login_allowed("192.168.1.20"))
        finally:
            server.server_close()

    def test_dashboard_migration_is_idempotent(self):
        first = migrate(self.db, seed=True)
        second = migrate(self.db, seed=True)
        self.assertEqual(first, {"chores": 6, "rewards": 2})
        self.assertEqual(second, {"chores": 0, "rewards": 0})

    def test_default_rewards_restore_an_individual_goal_for_each_child(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                "INSERT INTO reward_goals(member_id,title,emoji,goal_type,target_value,unit_label,created_at) VALUES(3,'Old', '🎯','points',30,'poeng','now')"
            )
            connection.execute("UPDATE reward_goals SET active=0")
        self.assertEqual(ensure_default_rewards(self.db), 2)
        dashboard = self.repo.dashboard(dt.date(2026, 8, 15))
        self.assertTrue(all(child["reward"] for child in dashboard["children"]))
        self.assertTrue(all(child["reward"]["target_value"] == 30 for child in dashboard["children"]))
        self.assertEqual(ensure_default_rewards(self.db), 0)

    def test_clear_setup_preserves_history_but_hides_active_setup(self):
        migrate(self.db, seed=True)
        with sqlite3.connect(self.db) as connection:
            card_id = connection.execute(
                """SELECT k.id FROM kanban_cards k
                   JOIN family_chore_meta m ON m.card_id=k.id
                   WHERE lower(k.assigned_to)='child one' LIMIT 1"""
            ).fetchone()[0]
        self.repo.complete_chore(card_id, {
            "member_id": 3, "idempotency_key": "preserved-history-key",
        })
        result = clear_active_setup(self.db)
        self.assertEqual(result, {"archived_chores": 6, "deactivated_rewards": 2})
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM chore_completions").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reward_goals WHERE active=1").fetchone()[0], 0)
        dashboard = self.repo.dashboard(dt.date(2026, 8, 15))
        self.assertTrue(all(not child["chores"] and child["reward"] is None and not child["history"] for child in dashboard["children"]))

    def test_parent_token_must_not_be_empty(self):
        server = FamilyApiServer(("127.0.0.1", 0), self.repo, "1234")
        try:
            self.assertEqual(server.parent_token, "")
            # The HTTP handler's explicit non-empty guard is a release boundary.
            source = Path(__file__).with_name("familybot_api.py").read_text(encoding="utf-8")
            self.assertIn("bool(supplied) and bool(self.app.parent_token)", source)
        finally:
            server.server_close()

    def test_current_week_plan_days_are_curated_for_child_page(self):
        with sqlite3.connect(self.db) as connection:
            cursor = connection.execute(
                """INSERT INTO week_plans(member_id,week_number,year,summary,raw_text,teacher)
                   VALUES(3,34,2026,'Kort sammendrag','Subject: Ukeplan [Attachment: private.pdf] Hele ukeplanen med lekser, beskjeder og detaljer fra parent@example.invalid.','Ingrid')"""
            )
            connection.execute(
                """INSERT INTO week_plan_days(week_plan_id,day,date,subject,homework,bring)
                   VALUES(?,?,?,?,?,?)""",
                (cursor.lastrowid, "onsdag", "2026-08-19", "Tur", "Leksefri", "Mat og drikke"),
            )
            connection.execute(
                """INSERT INTO week_plan_interpretations(
                       week_plan_id,status,source_hash,parser_version,structured_json)
                   VALUES(?,?,?,?,?)""",
                (cursor.lastrowid, "accepted", "test", "test", json.dumps({
                    "version": 2, "week": 34, "year": 2026,
                    "days": [{"date": "2026-08-19", "weekday": "onsdag", "items": [{
                        "category": "homework", "text": "Leksefri",
                        "source_blocks": ["page2-block1"], "confidence": 1,
                    }]}],
                    "weekly_tasks": [{"text": "Les side 10", "source_blocks": ["page2-block1"]}],
                    "general_info": [],
                })),
            )
        dashboard = self.repo.dashboard(dt.date(2026, 8, 15))
        self.assertEqual(dashboard["week_plan_days"][0]["member"], "Child One")
        self.assertEqual(dashboard["week_plan_days"][0]["homework"], "Leksefri")
        plan = self.repo.week_plan_detail(3, cursor.lastrowid)
        self.assertEqual(plan["full_text"], "Hele ukeplanen med lekser, beskjeder og detaljer fra .")
        self.assertEqual(plan["interpretation"]["days"][0]["items"][0]["text"], "Leksefri")
        self.assertEqual(plan["interpretation"]["weekly_tasks"][0]["text"], "Les side 10")
        self.assertNotIn("Subject:", plan["full_text"])
        self.assertNotIn("@", plan["full_text"])
        self.assertEqual(plan["days"][0]["homework"], "Leksefri")
        self.assertNotIn("full_text", json.dumps(dashboard))
        self.assertNotIn("raw_text", json.dumps(dashboard))

    def test_upcoming_week_uses_current_plan_until_next_plan_arrives(self):
        with sqlite3.connect(self.db) as connection:
            cursor = connection.execute(
                """INSERT INTO week_plans(member_id,week_number,year,summary,raw_text,teacher)
                   VALUES(3,35,2026,'Denne uken','Ukeplan for denne uken','Ingrid')"""
            )
            connection.execute(
                """INSERT INTO week_plan_days(week_plan_id,day,date,subject,homework,bring)
                   VALUES(?,?,?,?,?,?)""",
                (cursor.lastrowid, "fredag", "2026-08-28", "Oppsummering", "Les", "Bok"),
            )
        dashboard = self.repo.dashboard(dt.date(2026, 8, 28))
        self.assertEqual(dashboard["target_week"], {"week": 36, "year": 2026, "starts": "2026-08-31"})
        self.assertEqual(dashboard["week_plan_week"], {"week": 35, "year": 2026, "fallback": True})
        self.assertEqual(dashboard["week_plans"][0]["week_number"], 35)
        self.assertEqual(dashboard["week_plan_days"][0]["homework"], "Les")

    def test_transport_cache_exposes_only_curated_departure_fields(self):
        transport = transport_summary(Path(self.temp.name))
        self.assertEqual(transport["stop"], "Local Station")
        self.assertEqual(transport["departures"][0]["destination"], "City Terminus")
        self.assertEqual(transport["departures"][0]["platform"], "1")
        self.assertNotIn("serviceJourney", json.dumps(transport))

    def test_transport_contract_supports_configured_non_metro_mode(self):
        root = Path(self.temp.name)
        config_path = root / "config/family.local.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["integrations"]["transport"].update({"transport_mode": "bus", "line": "31"})
        config_path.write_text(json.dumps(config), encoding="utf-8")
        (root / "db/dashboard_departures.json").unlink()
        payload = {"data": {"stopPlace": {"estimatedCalls": [{
            "realtime": True,
            "aimedDepartureTime": "2026-08-17T20:00:00+02:00",
            "expectedDepartureTime": "2026-08-17T20:01:00+02:00",
            "destinationDisplay": {"frontText": "City centre"},
            "quay": {"id": "NSR:Quay:test", "publicCode": "B"},
            "serviceJourney": {"journeyPattern": {"line": {"publicCode": "31", "transportMode": "bus"}}},
        }]}}}
        response = io.BytesIO(json.dumps(payload).encode("utf-8"))
        with patch("familybot_api.urllib.request.urlopen", return_value=response):
            result = transport_summary(root)
        self.assertEqual(result["departures"][0]["line"], "31")
        self.assertEqual(result["departures"][0]["platform"], "B")

    def test_weather_request_uses_local_configuration(self):
        root = Path(self.temp.name)
        (root / "db/dashboard_weather.json").unlink()
        local_now = dt.datetime.now().astimezone()
        forecast_date = local_now.date()
        forecast_rows = []
        for hour, temperature, rain, symbol in ((8, 12, 0.4, "cloudy"), (12, 15, 0.0, "fair"), (16, 14, 0.2, "lightrain")):
            forecast_rows.append({
                "time": dt.datetime.combine(forecast_date, dt.time(hour=hour), tzinfo=local_now.tzinfo).isoformat(),
                "data": {
                    "instant": {"details": {"air_temperature": temperature}},
                    "next_1_hours": {
                        "summary": {"symbol_code": symbol},
                        "details": {"precipitation_amount": rain},
                    },
                },
            })
        payload = {
            "properties": {
                "meta": {"updated_at": "2026-08-17T10:00:00Z"},
                "timeseries": forecast_rows,
            },
        }
        response = io.BytesIO(json.dumps(payload).encode("utf-8"))
        with patch("familybot_api.urllib.request.urlopen", return_value=response) as opened:
            result = weather_summary(root)
        request = opened.call_args.args[0]
        self.assertIn("lat=1.25000&lon=2.50000", request.full_url)
        self.assertEqual(request.get_header("User-agent"), "FamilyBot-test/1.0 contact@example.invalid")
        self.assertEqual(result["temperature"], 12)
        self.assertNotIn("neste 6 t", result["status"])
        self.assertEqual([period["label"] for period in result["periods"]], ["08–12", "12–16", "16–20"])
        self.assertEqual(result["periods"][0]["precipitation_mm"], 0.4)
        self.assertIn("regnjakke", result["advice"])


if __name__ == "__main__":
    unittest.main()
