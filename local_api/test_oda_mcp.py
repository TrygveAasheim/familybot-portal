import json
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import oda_mcp


class OdaMcpClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.credentials = Path(self.temp.name) / "private/oda.json"
        self.client = oda_mcp.OdaMcpClient(
            "http://familie.local:8788/api/oda/oauth/callback",
            self.credentials,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_credentials_are_owner_only_and_status_never_exposes_tokens(self):
        self.client._save({"client_id": "client", "access_token": "secret", "expires_at": time.time() + 3600})
        self.assertEqual(self.credentials.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.credentials.parent.stat().st_mode & 0o777, 0o700)
        status = self.client.status()
        self.assertTrue(status["connected"])
        self.assertNotIn("access_token", status)
        self.assertNotIn("secret", json.dumps(status))

    def test_authorization_uses_dynamic_registration_state_and_pkce(self):
        registration = json.dumps({"client_id": "oda-client"}).encode()
        with patch.object(self.client, "_request", return_value=({}, registration)) as request:
            url = self.client.begin_authorization("http://familie.local:3000")
        request.assert_called_once()
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(query["client_id"], ["oda-client"])
        self.assertEqual(query["redirect_uri"], [self.client.callback_url])
        self.assertEqual(query["resource"], [oda_mcp.MCP_URL])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertNotIn("code_verifier", query)
        self.assertIn(query["state"][0], self.client._pending)

    def test_callback_exchanges_code_and_persists_rotating_tokens(self):
        self.client._save({"client_id": "oda-client", "redirect_uri": self.client.callback_url})
        with patch.object(self.client, "_request", return_value=({}, b"{}")):
            url = self.client.begin_authorization("http://familie.local:3000")
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        tokens = json.dumps({"access_token": "access", "refresh_token": "refresh", "expires_in": 1200}).encode()
        with patch.object(self.client, "_request", return_value=({}, tokens)) as request:
            origin = self.client.finish_authorization({"state": [state], "code": ["code"]})
        self.assertEqual(origin, "http://familie.local:3000")
        form = request.call_args.kwargs["form"]
        self.assertEqual(form["code"], "code")
        self.assertNotEqual(form["code_verifier"], "")
        stored = json.loads(self.credentials.read_text())
        self.assertEqual(stored["refresh_token"], "refresh")
        self.assertGreater(stored["expires_at"], time.time())

    def test_tool_call_initializes_session_and_prefers_structured_content(self):
        self.client._save({"client_id": "oda-client", "access_token": "access", "refresh_token": "refresh", "expires_at": time.time() + 3600})
        initialize = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": oda_mcp.MCP_PROTOCOL_VERSION}}).encode()
        tool = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"content": [], "structuredContent": {"result": [{"id": 7}]}}}).encode()
        responses = [
            ({"content-type": "application/json", "mcp-session-id": "session-1"}, initialize),
            ({"content-type": "application/json"}, b""),
            ({"content-type": "application/json"}, tool),
        ]
        with patch.object(self.client, "_request", side_effect=responses) as request:
            result = self.client.call_tool("likely_to_buy", {})
        self.assertEqual(result, {"result": [{"id": 7}]})
        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args.kwargs["headers"]["Mcp-Session-Id"], "session-1")
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer access")

    def test_product_inputs_are_bounded_before_network_access(self):
        with self.assertRaises(oda_mcp.OdaValidationError):
            self.client.search_products("x")
        with self.assertRaises(oda_mcp.OdaValidationError):
            self.client.change_product(1, 0)
        with self.assertRaises(oda_mcp.OdaValidationError):
            self.client.change_product(-1, 1)

    def test_recipe_operations_use_explicit_tools_and_bounded_portions(self):
        with patch.object(self.client, "call_tool", return_value={"recipes": []}) as tool:
            self.client.search_recipes("rask middag", size=6)
            tool.assert_called_once_with("recipe_search", {
                "query": "rask middag",
                "page": 1,
                "size": 6,
                "intent": "wants dinner recipes matching the household request",
            })
        with patch.object(self.client, "call_tool", return_value={"groups": []}) as tool:
            self.client.add_recipe(42, 5)
            tool.assert_called_once_with("manipulate_cart", {
                "operations": [{"recipeId": 42, "quantity": 1, "fromRecipePortions": 5}],
                "intent": "wants to add all ingredients for a selected dinner recipe",
            })
        with self.assertRaises(oda_mcp.OdaValidationError):
            self.client.search_recipes("x")
        with self.assertRaises(oda_mcp.OdaValidationError):
            self.client.add_recipe(42, 0)


if __name__ == "__main__":
    unittest.main()
