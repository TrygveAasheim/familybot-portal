"""Scheduled image warm-up must obey current account consent, not saved tokens."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prefetch_job", ROOT / "scripts/prefetch_hellofresh_images.py")
assert spec and spec.loader
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)


class PrefetchConsentTests(unittest.TestCase):
    def test_current_flags_gate_before_any_credential_or_provider_access(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "config").mkdir()
            (workspace / "credentials").mkdir()
            credential = workspace / "credentials/hellofresh-no.json"
            credential.write_text('{"fixture":"retained-not-to-be-read"}')
            for features in ({}, {"hellofresh": True}, {"hellofresh": True, "hellofresh_account": False},
                             {"hellofresh": False, "hellofresh_account": True},
                             {"hellofresh": True, "hellofresh_account": "true"},
                             {"hellofresh": True, "hellofresh_account": True}):
                with self.subTest(features=features):
                    (workspace / "config/family.local.json").write_text(json.dumps({
                        "members": [], "portal": {"features": features}}))
                    with patch.dict(os.environ, {"FAMILYBOT_WORKSPACE": str(workspace)}, clear=True), \
                            patch.object(job, "HelloFreshAccountClient") as client, \
                            patch.object(job, "HelloFreshImageCache") as cache, \
                            patch.object(job, "prefetch_upcoming_images", return_value={"available": 0, "requested": 0}) as warm:
                        client.return_value.status.return_value = {"connected": True}
                        self.assertEqual(0, job.main())
                        enabled = features.get("hellofresh") is True and features.get("hellofresh_account") is True
                        self.assertEqual(int(enabled), client.call_count)
                        self.assertEqual(int(enabled), warm.call_count)
                        self.assertEqual(int(enabled), cache.call_count)
                    self.assertEqual('{"fixture":"retained-not-to-be-read"}', credential.read_text())

    def test_missing_config_fails_closed_before_client_creation(self):
        with patch.object(job, "portal_settings", side_effect=RuntimeError), \
                patch.object(job, "HelloFreshAccountClient") as client:
            self.assertEqual(1, job.main())
            client.assert_not_called()

    def test_generated_prefetch_job_requires_both_flags(self):
        deploy = (ROOT / "scripts/deploy-local.sh").read_text()
        match = re.search(r'FEATURES="\$\(.*?<<\x27PY\x27\n(.*?)\nPY\n\)"', deploy, re.S)
        self.assertIsNotNone(match)
        assert match
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "family.json"
            for public, account in ((False, False), (False, True), (True, False), (True, True)):
                config.write_text(json.dumps({"portal": {"features": {
                    "hellofresh": public, "hellofresh_account": account}}}))
                result = subprocess.run([sys.executable, "-", str(config)], input=match.group(1),
                                        text=True, capture_output=True, check=True)
                self.assertEqual(public and account, "hellofresh_account" in result.stdout.splitlines())
        self.assertIn('grep -Fxq "hellofresh_account"; then\n  install -m 600 "$IMAGE_PLIST_TEMP"', deploy)
        self.assertIn('grep -Fxq "hellofresh_account"; then\n  for attempt in 1 2 3; do', deploy)
