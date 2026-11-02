import json
import io
import stat
import tempfile
import time
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from hellofresh_account import (
    HelloFreshAccountAuthRequired,
    HelloFreshAccountClient,
    HelloFreshAccountUnavailable,
    HelloFreshAccountValidation,
    _HttpError,
)


ACCESS = "aaaaaaaa.bbbbbbbb.cccccccc"
REFRESH = "dddddddd.eeeeeeee.ffffffff"


class FakeBrowserResponse:
    def __init__(self, status, payload, content_type="application/json"):
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.content = (
            json.dumps(payload).encode("utf-8")
            if isinstance(payload, (dict, list))
            else bytes(payload)
        )


class FakeBrowserSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def close(self):
        self.closed = True


class HelloFreshAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.credentials = Path(self.temp.name) / "credentials/hellofresh-no.json"
        self.client = HelloFreshAccountClient(self.credentials)

    def tearDown(self):
        self.temp.cleanup()

    def test_browser_completed_login_persists_tokens_only_with_owner_permissions(self):
        status = self.client.complete_login(
            {"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 900}
        )
        self.assertTrue(status["connected"])
        self.assertEqual(stat.S_IMODE(self.credentials.stat().st_mode), 0o600)
        saved = json.loads(self.credentials.read_text(encoding="utf-8"))
        self.assertEqual(saved["refresh_token"], REFRESH)
        serialized = json.dumps(saved)
        self.assertEqual(set(saved), {"access_token", "refresh_token", "expires_at"})
        restarted = HelloFreshAccountClient(self.credentials)
        self.assertTrue(restarted.status()["connected"])

    def test_completed_login_accepts_opaque_oauth_refresh_token(self):
        opaque_refresh = "renew/opaque+token=with%valid:punctuation~"
        status = self.client.complete_login(
            {
                "access_token": ACCESS,
                "refresh_token": opaque_refresh,
                "expires_in": 900,
            }
        )
        self.assertTrue(status["connected"])
        saved = json.loads(self.credentials.read_text(encoding="utf-8"))
        self.assertEqual(saved["refresh_token"], opaque_refresh)

    def test_completed_login_rejects_token_whitespace_and_control_characters(self):
        for unsafe_refresh in (
            "refresh token with spaces",
            "refresh-token\nwith-newline",
            "refresh-token\rwith-return",
            "refresh-token\twith-tab",
        ):
            with self.subTest(unsafe_refresh=repr(unsafe_refresh)):
                with self.assertRaises(HelloFreshAccountValidation):
                    self.client.complete_login(
                        {
                            "access_token": ACCESS,
                            "refresh_token": unsafe_refresh,
                            "expires_in": 900,
                        }
                    )
        self.assertFalse(self.credentials.exists())

    def test_completed_login_requires_access_and_refresh_tokens(self):
        with patch.object(self.client, "_save") as save:
            with self.assertRaises(HelloFreshAccountValidation):
                self.client.complete_login(None)
            with self.assertRaises(HelloFreshAccountValidation):
                self.client.complete_login({"access_token": ACCESS})
        save.assert_not_called()

    def test_transient_backend_login_uses_browser_transport_and_persists_tokens_only(self):
        session = FakeBrowserSession(
            [
                FakeBrowserResponse(401, {"error": "unauthorized"}),
                FakeBrowserResponse(
                    200,
                    {"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 900},
                ),
            ]
        )
        client = HelloFreshAccountClient(
            self.credentials, browser_session_factory=lambda: session
        )
        status = client.login(
            {"email": " Parent@Example.No ", "password": "unique-site-password"}
        )
        self.assertTrue(status["connected"])
        self.assertTrue(session.closed)
        self.assertEqual(session.calls[0][0], "https://www.hellofresh.no/gw/auth/token")
        login_url, login_request = session.calls[1]
        self.assertEqual(login_url, "https://www.hellofresh.no/gw/login")
        self.assertEqual(login_request["params"], {"country": "NO", "locale": "nb-NO"})
        self.assertEqual(
            login_request["json"],
            {"username": "parent@example.no", "password": "unique-site-password"},
        )
        self.assertEqual(login_request["headers"]["Origin"], "https://www.hellofresh.no")
        self.assertEqual(login_request["headers"]["Sec-Fetch-Site"], "same-origin")
        self.assertEqual(login_request["impersonate"], "chrome")
        self.assertTrue(login_request["verify"])
        saved = json.loads(self.credentials.read_text(encoding="utf-8"))
        self.assertEqual(set(saved), {"access_token", "refresh_token", "expires_at"})
        self.assertNotIn("parent@example.no", json.dumps(saved))
        self.assertNotIn("unique-site-password", json.dumps(saved))

    def test_transient_backend_login_distinguishes_rejection_from_provider_challenge(self):
        rejected = FakeBrowserSession(
            [
                FakeBrowserResponse(401, {"error": "unauthorized"}),
                FakeBrowserResponse(403, {"error": "access_denied"}),
            ]
        )
        client = HelloFreshAccountClient(
            self.credentials, browser_session_factory=lambda: rejected
        )
        with self.assertRaisesRegex(HelloFreshAccountValidation, "ikke godtatt"):
            client.login({"email": "parent@example.no", "password": "wrong"})
        self.assertFalse(self.credentials.exists())

        challenge = FakeBrowserSession(
            [
                FakeBrowserResponse(401, {"error": "unauthorized"}),
                FakeBrowserResponse(
                    403,
                    b"<title>Attention Required!</title><div id='cf-chl'>",
                    "text/html; charset=UTF-8",
                ),
            ]
        )
        client = HelloFreshAccountClient(
            self.credentials, browser_session_factory=lambda: challenge
        )
        with self.assertRaisesRegex(HelloFreshAccountUnavailable, "sikkerhetskontroll"):
            client.login({"email": "parent@example.no", "password": "correct"})
        self.assertFalse(self.credentials.exists())

        unknown_forbidden = FakeBrowserSession(
            [
                FakeBrowserResponse(401, {"error": "unauthorized"}),
                FakeBrowserResponse(403, {"error": "edge_policy"}),
            ]
        )
        client = HelloFreshAccountClient(
            self.credentials, browser_session_factory=lambda: unknown_forbidden
        )
        with self.assertRaisesRegex(HelloFreshAccountUnavailable, "innloggingskanalen"):
            client.login({"email": "parent@example.no", "password": "correct"})
        self.assertFalse(self.credentials.exists())

    def test_transient_backend_login_validates_email_and_password_before_provider_call(self):
        factory_calls = []
        client = HelloFreshAccountClient(
            self.credentials, browser_session_factory=lambda: factory_calls.append(True)
        )
        for payload in (
            {"email": "invalid", "password": "password"},
            {"email": "parent@example.no", "password": ""},
            {"email": "parent@example.no", "password": "x" * 513},
        ):
            with self.subTest(payload=set(payload)), self.assertRaises(
                HelloFreshAccountValidation
            ):
                client.login(payload)
        self.assertEqual(factory_calls, [])

    def test_http_error_classifies_cloudflare_html_challenge_without_retaining_body(self):
        headers = Message()
        headers["Content-Type"] = "text/html; charset=UTF-8"
        error = urllib.error.HTTPError(
            "https://www.hellofresh.no/gw/login",
            403,
            "Forbidden",
            headers,
            io.BytesIO(b"<title>Attention Required! | Cloudflare</title><div id='cf-chl'>"),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(_HttpError) as caught:
                self.client._request_json("/gw/login", method="POST", json_value={})
        self.assertEqual(caught.exception.status, 403)
        self.assertTrue(caught.exception.challenge)
        self.assertIsNone(caught.exception.code)

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

    def test_refresh_auth_rejection_forgets_tokens_and_requires_login(self):
        self.client._save({"refresh_token": REFRESH, "expires_at": time.time() - 1})
        with patch.object(self.client, "_guest_token", return_value=ACCESS), patch.object(
            self.client, "_request_json", side_effect=_HttpError(401)
        ):
            with self.assertRaises(HelloFreshAccountAuthRequired):
                self.client._refresh(self.client._load())
        self.assertFalse(self.credentials.exists())

    def test_refresh_temporary_failure_keeps_tokens_for_retry(self):
        self.client._save({"refresh_token": REFRESH, "expires_at": time.time() - 1})
        with patch.object(self.client, "_guest_token", return_value=ACCESS), patch.object(
            self.client, "_request_json", side_effect=_HttpError(503)
        ):
            with self.assertRaises(HelloFreshAccountUnavailable):
                self.client._refresh(self.client._load())
        self.assertEqual(self.client._load()["refresh_token"], REFRESH)
        self.assertTrue(self.client.status()["connected"])

    def test_refresh_cloudflare_challenge_keeps_tokens_for_retry(self):
        self.client._save({"refresh_token": REFRESH, "expires_at": time.time() - 1})
        with patch.object(self.client, "_guest_token", return_value=ACCESS), patch.object(
            self.client, "_request_json", side_effect=_HttpError(403, challenge=True)
        ):
            with self.assertRaises(HelloFreshAccountUnavailable):
                self.client._refresh(self.client._load())
        self.assertEqual(self.client._load()["refresh_token"], REFRESH)

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
