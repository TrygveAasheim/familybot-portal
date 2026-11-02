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
    _HttpError,
)


ACCESS = "aaaaaaaa.bbbbbbbb.cccccccc"
REFRESH = "dddddddd.eeeeeeee.ffffffff"


class HelloFreshAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.credentials = Path(self.temp.name) / "credentials/hellofresh-no.json"
        self.client = HelloFreshAccountClient(self.credentials)

    def tearDown(self):
        self.temp.cleanup()

    def test_login_persists_tokens_only_with_owner_permissions(self):
        with patch.object(self.client, "_guest_token", return_value=ACCESS), patch.object(
            self.client,
            "_request_json",
            return_value={"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 900},
        ) as request:
            status = self.client.login("Family@Example.no", "not-stored-password")
        self.assertTrue(status["connected"])
        self.assertEqual(stat.S_IMODE(self.credentials.stat().st_mode), 0o600)
        saved = json.loads(self.credentials.read_text(encoding="utf-8"))
        self.assertEqual(saved["refresh_token"], REFRESH)
        serialized = json.dumps(saved)
        self.assertNotIn("not-stored-password", serialized)
        self.assertNotIn("family@example.no", serialized)
        self.assertEqual(
            request.call_args.kwargs["json_value"],
            {"username": "family@example.no", "password": "not-stored-password"},
        )
        restarted = HelloFreshAccountClient(self.credentials)
        self.assertTrue(restarted.status()["connected"])

    def test_login_validates_email_and_password_without_calling_provider(self):
        with patch.object(self.client, "_request_json") as request:
            with self.assertRaises(HelloFreshAccountValidation):
                self.client.login("not-an-email", "password")
            with self.assertRaises(HelloFreshAccountValidation):
                self.client.login("family@example.no", "")
        request.assert_not_called()

    def test_login_maps_provider_rejection_without_saving_credentials(self):
        with patch.object(self.client, "_guest_token", return_value=ACCESS), patch.object(
            self.client, "_request_json", side_effect=_HttpError(403)
        ):
            with self.assertRaises(HelloFreshAccountAuthRequired):
                self.client.login("family@example.no", "wrong-password")
        self.assertFalse(self.credentials.exists())

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
