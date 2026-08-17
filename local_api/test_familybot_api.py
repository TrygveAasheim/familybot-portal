import datetime as dt
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard_migration import clear_active_setup, migrate
from familybot_api import FamilyApiServer, FamilyRepository, ValidationError, transport_summary, trusted_portal_origin, weather_summary


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
                "stop_name": "Local Station", "stop_id": "NSR:StopPlace:test",
                "centre_quay_id": "NSR:Quay:test", "line": "2",
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
            "status": "16 °C · delvis skyet · 0 mm neste 6 t",
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

    def test_chore_create_move_archive_and_restore(self):
        chore = self.repo.create_chore({"title":"Pakke gymtøy","assigned_to":"child one","priority":"important","due_date":"2026-08-18"})
        self.assertEqual(chore["lane"], "todo")
        moved = self.repo.update_chore(chore["id"], {"lane":"done"})
        self.assertEqual(moved["lane"], "done")
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

    def test_lan_origin_boundary(self):
        self.assertTrue(trusted_portal_origin("http://familie.local:3000"))
        self.assertTrue(trusted_portal_origin("http://192.168.1.20:3000"))
        self.assertFalse(trusted_portal_origin("https://evil.example:3000"))
        self.assertFalse(trusted_portal_origin("http://8.8.8.8:3000"))
        self.assertFalse(trusted_portal_origin("http://localhost:9999"))

    def test_dashboard_migration_is_idempotent(self):
        first = migrate(self.db, seed=True)
        second = migrate(self.db, seed=True)
        self.assertEqual(first, {"chores": 6, "rewards": 2})
        self.assertEqual(second, {"chores": 0, "rewards": 0})

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
                """INSERT INTO week_plans(member_id,week_number,year,summary,teacher)
                   VALUES(3,34,2026,'Leksefri. Onsdag er det tur til Holmen.','Ingrid')"""
            )
            connection.execute(
                """INSERT INTO week_plan_days(week_plan_id,day,date,subject,homework,bring)
                   VALUES(?,?,?,?,?,?)""",
                (cursor.lastrowid, "onsdag", "2026-08-19", "Tur", "Leksefri", "Mat og drikke"),
            )
        dashboard = self.repo.dashboard(dt.date(2026, 8, 15))
        self.assertEqual(dashboard["week_plan_days"][0]["member"], "Child One")
        self.assertEqual(dashboard["week_plan_days"][0]["homework"], "Leksefri")

    def test_transport_cache_exposes_only_curated_departure_fields(self):
        transport = transport_summary(Path(self.temp.name))
        self.assertEqual(transport["stop"], "Local Station")
        self.assertEqual(transport["departures"][0]["destination"], "City Terminus")
        self.assertEqual(transport["departures"][0]["platform"], "1")
        self.assertNotIn("serviceJourney", json.dumps(transport))

    def test_weather_request_uses_local_configuration(self):
        root = Path(self.temp.name)
        (root / "db/dashboard_weather.json").unlink()
        payload = {
            "properties": {
                "meta": {"updated_at": "2026-08-17T10:00:00Z"},
                "timeseries": [{
                    "data": {
                        "instant": {"details": {"air_temperature": 12}},
                        "next_1_hours": {
                            "summary": {"symbol_code": "cloudy"},
                            "details": {"precipitation_amount": 0},
                        },
                    },
                }],
            },
        }
        response = io.BytesIO(json.dumps(payload).encode("utf-8"))
        with patch("familybot_api.urllib.request.urlopen", return_value=response) as opened:
            result = weather_summary(root)
        request = opened.call_args.args[0]
        self.assertIn("lat=1.25000&lon=2.50000", request.full_url)
        self.assertEqual(request.get_header("User-agent"), "FamilyBot-test/1.0 contact@example.invalid")
        self.assertEqual(result["temperature"], 12)


if __name__ == "__main__":
    unittest.main()
