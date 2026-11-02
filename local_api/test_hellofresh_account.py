import json
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from hellofresh_account import (
    HelloFreshAccountAuthRequired,
    HelloFreshAccountClient,
    HelloFreshAccountValidation,
)


ACCESS = "aaaaaaaa.bbbbbbbb.cccccccc"
REFRESH = "dddddddd.eeeeeeee.ffffffff"


class HelloFreshAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.credentials = Path(self.temp.name) / "credentials/hellofresh-no.json"
        self.client = HelloFreshAccountClient(
            "http://familie.local:8788/api/hellofresh/auth/callback",
            self.credentials,
        )

    def tearDown(self):
        self.temp.cleanup()

    def begin(self):
        with patch.object(self.client, "_send_magic_link") as send:
            result = self.client.begin_login("Family@Example.no", "http://familie.local:3000")
        self.assertTrue(result["sent"])
        self.assertTrue(result["automatic_return"])
        self.assertEqual(send.call_count, 1)
        return json.loads(self.credentials.read_text(encoding="utf-8"))["pending"]

    def test_begin_login_persists_only_pending_state_with_owner_permissions(self):
        self.client._save({"access_token": ACCESS, "refresh_token": REFRESH, "expires_at": time.time() + 300})
        pending = self.begin()
        self.assertEqual(pending["email"], "family@example.no")
        self.assertEqual(stat.S_IMODE(self.credentials.stat().st_mode), 0o600)
        saved = json.loads(self.credentials.read_text(encoding="utf-8"))
        self.assertNotIn("access_token", saved)
        self.assertNotIn("refresh_token", saved)
        self.assertEqual(
            self.client.status(),
            {
                "connected": False,
                "pending": True,
                "automatic_return": True,
                "credentials_local": True,
                "read_only": True,
            },
        )
        self.assertNotIn("email", self.client.status())

    def test_callback_persists_refresh_credential_and_survives_restart(self):
        pending = self.begin()
        query = {
            "code": ["one-time-code"],
            "email": [pending["email"]],
            "public_id": [pending["public_id"]],
        }
        with patch.object(self.client, "_guest_token", return_value=ACCESS), patch.object(
            self.client,
            "_request_json",
            return_value={"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 900},
        ):
            origin = self.client.finish_callback(query)
        self.assertEqual(origin, "http://familie.local:3000")
        saved = json.loads(self.credentials.read_text(encoding="utf-8"))
        self.assertEqual(saved["refresh_token"], REFRESH)
        self.assertNotIn("pending", saved)
        restarted = HelloFreshAccountClient(self.client.callback_url, self.credentials)
        self.assertTrue(restarted.status()["connected"])

    def test_callback_rejects_a_different_login_correlation(self):
        pending = self.begin()
        with self.assertRaises(HelloFreshAccountAuthRequired):
            self.client.finish_callback({
                "code": ["one-time-code"],
                "email": [pending["email"]],
                "public_id": ["different-public-id"],
            })

    def test_pasted_link_rejects_untrusted_hosts(self):
        with self.assertRaises(HelloFreshAccountValidation):
            self.client.finish_magic_link(
                "https://example.invalid/login?code=secret&email=family@example.no&public_id=12345678"
            )

    def test_refresh_replaces_tokens_in_owner_only_file(self):
        self.client._save({"refresh_token": REFRESH, "expires_at": time.time() - 1})
        with patch.object(self.client, "_guest_token", return_value=ACCESS), patch.object(
            self.client,
            "_request_json",
            return_value={"access_token": ACCESS, "refresh_token": ACCESS, "expires_in": 600},
        ):
            refreshed = self.client._refresh(self.client._load())
        self.assertEqual(refreshed["refresh_token"], ACCESS)
        self.assertEqual(stat.S_IMODE(self.credentials.stat().st_mode), 0o600)

    def test_account_menu_is_curated_and_includes_selected_quantity(self):
        responses = iter([
            {"activeSubscriptionId": "sub-secret", "activeSubscriptionSkus": ["classic-box"]},
            {"menu": {"week": "2026-W46", "meals": [{
                "index": 2,
                "selection": {"quantity": 2},
                "recipe": {
                    "id": "0123456789abcdef01234567",
                    "name": "Laks med poteter",
                    "headline": "En enkel familiemiddag",
                    "imageLink": "https://cdn.hellofresh.com/hellofresh_s3/image/test.jpg",
                    "prepTime": "PT30M",
                    "difficulty": 1,
                    "tags": [{"name": "Familievennlig", "displayLabel": True}],
                },
            }]}}
        ])
        with patch.object(self.client, "_authorized_json", side_effect=lambda *_args, **_kwargs: next(responses)):
            menu = self.client.menu("2026-W46")
        self.assertEqual(menu["selected_count"], 2)
        self.assertEqual(menu["recipes"][0]["selected_quantity"], 2)
        serialized = json.dumps(menu)
        self.assertNotIn("sub-secret", serialized)
        self.assertNotIn("classic-box", serialized)


if __name__ == "__main__":
    unittest.main()
