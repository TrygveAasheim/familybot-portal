"""Acceptance evidence must be explicit, profile-aware and fresh."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("acceptance", ROOT / "tests/acceptance.py")
assert spec and spec.loader
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class AcceptanceTests(unittest.TestCase):
    def test_retained_plan_stays_applicable_with_ingestion_omitted_or_disabled(self):
        import test_familybot_api as api_tests

        fixture = api_tests.RepositoryTests()
        fixture.setUp()
        try:
            config_path = fixture.repo.workspace / "config/family.local.json"
            config = json.loads(config_path.read_text())
            today = dt.date.today()
            target = today + dt.timedelta(days=7 - today.weekday()) if today.weekday() >= 5 else today
            year, week, _ = target.isocalendar()
            with fixture.repo.connect() as connection:
                connection.execute(
                    "INSERT INTO week_plans(id,member_id,week_number,year,raw_text,summary) VALUES(111,3,?,?,?,?)",
                    (week, year, "Fictional retained plan", "Fictional retained plan"))
            for integrations in ({}, {"email": {"enabled": False}}):
                with self.subTest(integrations=integrations):
                    config["profile"] = "connected"
                    config["integrations"] = integrations
                    config_path.write_text(json.dumps(config))
                    with patch.dict(os.environ, {}, clear=True), \
                            patch.object(api_tests.FamilyRepository, "_launchd_state", return_value={}), \
                            patch("urllib.request.urlopen", side_effect=AssertionError("No network permitted")):
                        dashboard = fixture.repo.dashboard()
                        detail = fixture.repo.week_plan_detail(3, 111)
                    self.assertIn(111, [p["id"] for p in dashboard["week_plans"]])
                    self.assertEqual("Fictional retained plan", detail["full_text"])
                    self.assertEqual("not_run", acceptance.applicability(config)["AC-17"]["status"])
        finally:
            fixture.tearDown()

    def test_api_runner_does_not_inherit_household_overrides(self):
        runner_spec = importlib.util.spec_from_file_location("test_api_runner", ROOT / "scripts/test_api.py")
        assert runner_spec and runner_spec.loader
        runner = importlib.util.module_from_spec(runner_spec)
        runner_spec.loader.exec_module(runner)
        with patch.dict(os.environ, {"FAMILYBOT_FAMILY_CONFIG": "/fictional/do-not-read.json",
                                    "FAMILYBOT_DB_PATH": "/fictional/do-not-open.db",
                                    "FAMILYBOT_ODA_CREDENTIALS": "/fictional/do-not-read-credentials.json",
                                    "OPENCLAW_WORKSPACE": "/fictional/legacy"}):
            environment = runner.test_environment(Path("/fictional/test-workspace"))
        self.assertEqual({"FAMILYBOT_WORKSPACE": "/fictional/test-workspace"},
                         {k: v for k, v in environment.items() if k.startswith("FAMILYBOT_")})
        self.assertNotIn("OPENCLAW_WORKSPACE", environment)

    def test_explicit_target_required_before_runtime_access(self):
        result = subprocess.run([sys.executable, str(ROOT / "tests/acceptance.py")],
                                capture_output=True, text=True, check=False)
        self.assertEqual(2, result.returncode)
        self.assertIn("--workspace", result.stderr)
        self.assertIn("--host", result.stderr)

    def test_household_sizes_custom_rewards_and_no_old_browser_evidence(self):
        for count in (0, 1, 3):
            with self.subTest(children=count), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "config").mkdir()
                (root / "db").mkdir()
                children = [{"id": n + 2, "reward": {"earned": 0, "remaining": 45, "percent": 0,
                                                    "target_value": 45, "title": "Fictional reward"}}
                            for n in range(count)]
                config = {"profile": "dashboard", "members": [{"member_id": 1, "role": "parent"}]
                          + [{"member_id": c["id"], "role": "child"} for c in children],
                          "portal": {"hostname": "test.local", "web_port": 3100, "api_port": 8799,
                                     "allowed_origins": ["http://test.local:3100"]}, "integrations": {}}
                path = root / "config/family.local.json"
                path.write_text(json.dumps(config))
                path.chmod(0o600)
                for relative in ("config/parent-pin.txt", "db/family.db"):
                    path = root / relative
                    path.touch(mode=0o600)

                def request(host, port, route, origin, token=""):
                    self.assertEqual("127.0.0.1", host)
                    if origin == "https://invalid.example" or (route == "/api/dashboard" and not token):
                        return 403, b"{}"
                    if route == "/":
                        return 200, b"<html>Familieportalen</html>"
                    payload = {
                        "/api/health": {"ok": True, "service": "familybot-dashboard-api"},
                        "/api/session": {"token": "test-token", "api": "familybot-local-v2", "features": {
                            "oda": False, "oda_ai": False, "hellofresh": False, "hellofresh_account": False}},
                        "/api/dashboard": {"children": children},
                    }
                    self.assertIn(route, payload, "No optional provider route may be probed")
                    return 200, json.dumps(payload[route]).encode()

                with patch.object(acceptance, "request", side_effect=request):
                    report = acceptance.probe(root, "127.0.0.1")
                self.assertTrue(report["automated_checks_ok"])
                self.assertFalse(report["release_ready"])
                self.assertEqual("not_run", report["criteria"]["AC-09"]["status"])
                self.assertEqual("not_applicable", report["criteria"]["AC-18"]["status"])
                self.assertEqual("not_run" if count else "not_applicable", report["criteria"]["AC-17"]["status"])
                self.assertEqual("not_run" if count else "not_applicable", report["criteria"]["AC-03"]["status"])

    def test_integrations_require_consent_before_any_http_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config/family.local.json").write_text(json.dumps({"integrations": {"weather": {"enabled": True}}}))
            with patch.object(acceptance, "request") as request, self.assertRaises(ValueError):
                acceptance.probe(root, "localhost")
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
