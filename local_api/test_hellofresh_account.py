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
    HelloFreshAccountConflict,
    HelloFreshAccountUnavailable,
    HelloFreshAccountValidation,
    _HttpError,
)


ACCESS = "aaaaaaaa.bbbbbbbb.cccccccc"
REFRESH = "dddddddd.eeeeeeee.ffffffff"


def account_subscription():
    return {
        "id": "subscription-secret",
        "isActive": True,
        "customer": {"id": "customer-secret"},
        "product": {"sku": "NO-BOX-3-4-0"},
        "productType": {"specs": {"meals": 3, "size": 4}},
        "preset": "quick",
        "nextModifiableDeliveryWeek": "2026-W46",
        "weekWithLatestMenu": "2026-W49",
    }


def delivery_week(status="RUNNING"):
    return {
        "id": "2026-W46",
        "subscriptionId": "subscription-secret",
        "deliveryDate": "2099-11-09T12:00:00+01:00",
        "cutoffDate": "2099-11-03T23:59:59+01:00",
        "status": status,
        "state": status,
        "deliveryBlocked": False,
        "allowedActions": {"mealSwap": True, "pause": True},
        "product": {"handle": "NO-BOX-3-4-0", "specs": {"meals": 3, "size": 4}},
    }


def menu_payload(selected=(1, 2, 6), *, include_extra=True):
    meals = []
    for order, index in enumerate((1, 2, 3, 4, 5, 52, 29, 45, 6)):
        meals.append(
            {
                "index": index,
                "selection": {"limit": 10, **({"quantity": 1} if index in selected else {})},
                "recipe": {
                    "id": f"{index:024x}",
                    "name": f"Rett {index}",
                    "headline": f"Middag nummer {index}",
                    "image": f"https://img.hellofresh.com/test/{index}.jpg",
                    "prepTime": "PT30M",
                    "difficulty": 1,
                    "tags": [{"name": "Familievennlig", "displayLabel": True}],
                },
            }
        )
    groups = []
    if include_extra:
        groups = [{
            "groupType": "protein",
            "sku": "NO-EXTRA",
            "addOns": [{
                "index": 1001,
                "selection": {"oneOffQuantity": 1, "preselectedQuantity": 0, "courses": [{"index": 1}]},
            }],
        }]
    return {
        "id": "menu-secret",
        "week": "2026-W46",
        "meals": meals,
        "addOns": {"groups": groups},
    }


def menu_bundle(selected=(1, 2, 6), *, status="RUNNING"):
    return {
        "week": "2026-W46",
        "subscription": account_subscription(),
        "delivery": delivery_week(status),
        "payload": menu_payload(selected),
        "product_handle": f"NO-BOX-{len(selected)}-4-0",
        "product_options": {2: "NO-BOX-2-4-0", 3: "NO-BOX-3-4-0", 4: "NO-BOX-4-4-0", 5: "NO-BOX-5-4-0"},
        "servings": 4,
    }


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

    def test_authorized_write_retries_once_with_same_body_after_access_refresh(self):
        credentials = {
            "access_token": ACCESS,
            "refresh_token": REFRESH,
            "expires_at": time.time() + 600,
        }
        replacement = {**credentials, "access_token": "newaccess.token.value"}
        body = {"meals": [{"index": 1, "quantity": 1}]}
        with patch.object(self.client, "_load", return_value=credentials), patch.object(
            self.client, "_refresh", return_value=replacement
        ) as refresh, patch.object(
            self.client, "_request_json", side_effect=[_HttpError(401), {"ok": True}]
        ) as request:
            result = self.client._authorized_json(
                "/gw/v1/carts/2026-W46",
                method="PUT",
                params={"week": "2026-W46"},
                json_value=body,
                extra_headers={"x-requested-by": "shopping-experience-web"},
            )
        self.assertEqual(result, {"ok": True})
        refresh.assert_called_once_with(credentials)
        self.assertEqual(request.call_count, 2)
        for call in request.call_args_list:
            self.assertEqual(call.kwargs["method"], "PUT")
            self.assertEqual(call.kwargs["json_value"], body)
            self.assertEqual(call.kwargs["params"], {"week": "2026-W46"})
            self.assertEqual(
                call.kwargs["extra_headers"],
                {"x-requested-by": "shopping-experience-web"},
            )
        self.assertEqual(request.call_args_list[0].kwargs["bearer"], ACCESS)
        self.assertEqual(
            request.call_args_list[1].kwargs["bearer"], "newaccess.token.value"
        )

    def test_authorized_forbidden_response_keeps_renewable_credentials(self):
        credentials = {
            "access_token": ACCESS,
            "refresh_token": REFRESH,
            "expires_at": time.time() + 600,
        }
        with patch.object(self.client, "_load", return_value=credentials), patch.object(
            self.client, "_request_json", side_effect=_HttpError(403)
        ), patch.object(self.client, "disconnect") as disconnect:
            with self.assertRaises(HelloFreshAccountUnavailable):
                self.client._authorized_json("/gw/api/customers/me/deliveries")
        disconnect.assert_not_called()

    def test_account_menu_is_curated_and_includes_selected_quantity(self):
        with patch.object(self.client, "_menu_bundle", return_value=menu_bundle()):
            menu = self.client.menu("2026-W46")
        self.assertEqual(menu["selected_count"], 3)
        self.assertEqual([item["course_index"] for item in menu["recipes"][:3]], [1, 2, 6])
        self.assertTrue(all(item["image_url"].startswith("https://img.hellofresh.com/") for item in menu["recipes"]))
        self.assertEqual(menu["available_meal_counts"], [2, 3, 4, 5])
        self.assertTrue(menu["editable"])
        self.assertRegex(menu["selection_snapshot"], r"^[0-9a-f]{64}$")
        serialized = json.dumps(menu)
        self.assertNotIn("subscription-secret", serialized)
        self.assertNotIn("customer-secret", serialized)
        self.assertNotIn("NO-BOX", serialized)

    def test_upcoming_weeks_start_on_next_modifiable_and_mark_publication(self):
        subscription = account_subscription()
        deliveries = [delivery_week(), {**delivery_week(), "id": "2026-W50"}]
        with patch.object(self.client, "_active_subscription", return_value=subscription), patch.object(
            self.client, "_delivery_weeks", return_value=deliveries
        ) as read_weeks:
            result = self.client.weeks()
        # HelloFresh treats rangeStart as exclusive, so the client brackets
        # the provider's next modifiable week with the preceding ISO week.
        self.assertEqual(read_weeks.call_args.args[0], "2026-W45")
        self.assertEqual(result["default_week"], "2026-W46")
        self.assertTrue(result["weeks"][0]["menu_published"])
        self.assertFalse(result["weeks"][1]["menu_published"])
        self.assertNotIn("subscription-secret", json.dumps(result))

    def test_paused_next_modifiable_week_remains_the_default(self):
        paused = delivery_week("PAUSED")
        later = {**delivery_week(), "id": "2026-W47"}
        with patch.object(
            self.client, "_active_subscription", return_value=account_subscription()
        ), patch.object(self.client, "_delivery_weeks", return_value=[paused, later]):
            result = self.client.weeks()
        self.assertEqual(result["default_week"], "2026-W46")

    def test_product_options_require_active_subscribable_matching_size(self):
        products = [
            {"handle": "valid", "isActive": True, "isSubscribable": True, "specs": {"meals": 3, "size": 4}},
            {"handle": "inactive", "isActive": False, "isSubscribable": True, "specs": {"meals": 4, "size": 4}},
            {"handle": "not-subscribable", "isActive": True, "isSubscribable": False, "specs": {"meals": 5, "size": 4}},
            {"handle": "wrong-size", "isActive": True, "isSubscribable": True, "specs": {"meals": 2, "size": 2}},
        ]
        with patch.object(
            self.client, "_authorized_json", return_value={"items": [{"products": products}]}
        ):
            result = self.client._product_options("subscription-secret", 4)
        self.assertEqual(result, {3: "valid"})

    def test_single_week_lookup_brackets_exclusive_provider_range(self):
        delivery = delivery_week()
        with patch.object(
            self.client, "_delivery_weeks", return_value=[delivery]
        ) as read_weeks:
            result = self.client._delivery_week("2026-W46")
        self.assertEqual(result["id"], "2026-W46")
        read_weeks.assert_called_once_with("2026-W45", "2026-W47")

    def test_replace_preserves_unrelated_meals_and_selected_extras(self):
        before = menu_bundle()
        after = menu_bundle((1, 3, 6))
        snapshot = self.client._menu_snapshot(
            "2026-W46", before["payload"], before["delivery"], before["product_handle"]
        )
        with patch.object(self.client, "_menu_bundle", side_effect=[before, after]), patch.object(
            self.client, "_authorized_json", return_value={"hasSeamlessDowngraded": False}
        ) as provider:
            menu = self.client.change_selection(
                "2026-W46",
                {"snapshot": snapshot, "from_course_index": 2, "to_course_index": 3},
                "replace",
            )
        self.assertEqual(menu["selected_count"], 3)
        write = provider.call_args
        self.assertEqual(write.args[0], "/gw/v1/carts/2026-W46")
        self.assertEqual(write.kwargs["method"], "PUT")
        self.assertEqual(
            write.kwargs["json_value"]["meals"],
            [{"index": 1, "quantity": 1}, {"index": 3, "quantity": 1}, {"index": 6, "quantity": 1}],
        )
        self.assertEqual(write.kwargs["json_value"]["extras"][0]["selection"][0]["index"], 1001)
        self.assertEqual(write.kwargs["params"]["product-sku"], "NO-BOX-3-4-0")
        self.assertEqual(write.kwargs["extra_headers"], {"x-requested-by": "shopping-experience-web"})

    def test_add_and_remove_select_matching_one_week_box_sizes(self):
        for action, payload, before_selected, after_selected, expected_sku in (
            ("add", {"course_index": 3}, (1, 2, 6), (1, 2, 3, 6), "NO-BOX-4-4-0"),
            ("remove", {"course_index": 2}, (1, 2, 6), (1, 6), "NO-BOX-2-4-0"),
        ):
            with self.subTest(action=action):
                before = menu_bundle(before_selected)
                after = menu_bundle(after_selected)
                after["product_handle"] = expected_sku
                snapshot = self.client._menu_snapshot(
                    "2026-W46", before["payload"], before["delivery"], before["product_handle"]
                )
                with patch.object(self.client, "_menu_bundle", side_effect=[before, after]), patch.object(
                    self.client, "_authorized_json", return_value={"hasSeamlessDowngraded": False}
                ) as provider:
                    self.client.change_selection(
                        "2026-W46", {"snapshot": snapshot, **payload}, action
                    )
                self.assertEqual(provider.call_args.kwargs["params"]["product-sku"], expected_sku)

    def test_stale_selection_snapshot_blocks_provider_write(self):
        before = menu_bundle()
        with patch.object(self.client, "_menu_bundle", return_value=before), patch.object(
            self.client, "_authorized_json"
        ) as provider:
            with self.assertRaises(HelloFreshAccountConflict):
                self.client.change_selection(
                    "2026-W46",
                    {"snapshot": "0" * 64, "from_course_index": 1, "to_course_index": 3},
                    "replace",
                )
        provider.assert_not_called()

    def test_delivery_from_another_subscription_blocks_provider_write(self):
        before = menu_bundle()
        before["delivery"] = {**before["delivery"], "subscriptionId": "other-subscription"}
        with patch.object(self.client, "_active_subscription", return_value=before["subscription"]), patch.object(
            self.client, "_delivery_week", return_value=before["delivery"]
        ), patch.object(self.client, "_authorized_json") as provider:
            with self.assertRaises(HelloFreshAccountUnavailable):
                self.client._menu_bundle("2026-W46")
        provider.assert_not_called()

    def test_pause_writes_exact_week_and_verifies_status(self):
        before = delivery_week()
        after = delivery_week("PAUSED")
        snapshot = self.client._week_snapshot(before)
        with patch.object(self.client, "_active_subscription", return_value=account_subscription()), patch.object(
            self.client, "_delivery_week", side_effect=[before, after]
        ), patch.object(self.client, "_authorized_json", return_value={"items": [after]}) as provider:
            result = self.client.set_week_paused(
                "2026-W46", {"paused": True, "snapshot": snapshot}
            )
        self.assertTrue(result["paused"])
        self.assertEqual(
            provider.call_args.args[0],
            "/gw/api/subscriptions/subscription-secret/delivery_dates/2026-W46",
        )
        self.assertEqual(provider.call_args.kwargs["method"], "PATCH")
        self.assertEqual(provider.call_args.kwargs["json_value"]["delivery"]["status"], "PAUSED")


if __name__ == "__main__":
    unittest.main()
