import json
import time
import unittest
from unittest.mock import patch

from hellofresh_norway import (
    CACHE_SECONDS,
    HelloFreshNorwayClient,
    HelloFreshUnavailable,
)


def menu_html(*, country="NO", locale="nb-NO", image_host="d3hvwccx09j84u.cloudfront.net"):
    recipe_id = "672a136d12c55222c8cc8991"
    next_data = {
        "props": {
            "pageProps": {
                "ssrPayload": {
                    "systemCountry": country,
                    "locale": locale,
                    "activeWeek": "2026-W46",
                    "serverAuth": {"access_token": "must-never-reach-the-browser"},
                    "courses": [{
                        "index": 2,
                        "isSoldOut": False,
                        "chargeSetting": {"amount": 6995},
                        "recipe": {
                            "id": recipe_id,
                            "name": "  Stekt laks   og salat  ",
                            "headline": "med pære og valnøtter",
                            "websiteUrl": f"https://www.hellofresh.no/recipes/stekt-laks-{recipe_id}",
                            "imageLink": f"https://{image_host}/0,0/image/laks.jpg",
                            "prepTime": "PT25M",
                            "difficulty": 1,
                            "nutrition": [{"name": "Kalorier", "amount": 640, "unit": "kcal"}],
                            "tags": [
                                {"name": "Rask", "displayLabel": True},
                                {"name": "internal", "displayLabel": False},
                            ],
                        },
                    }],
                },
            },
        },
    }
    return (
        "<!doctype html><html><head></head><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'
        "</body></html>"
    )


class HelloFreshNorwayTests(unittest.TestCase):
    def test_public_norwegian_menu_is_reduced_to_curated_fields(self):
        client = HelloFreshNorwayClient()
        with patch.object(client, "_fetch_html", return_value=menu_html()):
            menu = client.menu()

        self.assertEqual(menu["week"], "2026-W46")
        self.assertTrue(menu["read_only"])
        self.assertEqual(menu["recipes"][0]["name"], "Stekt laks og salat")
        self.assertEqual(menu["recipes"][0]["tags"], ["Rask"])
        self.assertEqual(menu["recipes"][0]["calories"], 640)
        self.assertEqual(menu["recipes"][0]["extra_charge_ore"], 6995)
        encoded = json.dumps(menu)
        self.assertNotIn("access_token", encoded)
        self.assertNotIn("must-never", encoded)
        self.assertNotIn("websiteUrl", encoded)

    def test_non_norwegian_payload_is_rejected(self):
        client = HelloFreshNorwayClient()
        with patch.object(client, "_fetch_html", return_value=menu_html(country="US", locale="en-US")):
            with self.assertRaisesRegex(HelloFreshUnavailable, "norske menyen"):
                client.menu()

    def test_unapproved_image_host_is_removed(self):
        client = HelloFreshNorwayClient()
        with patch.object(client, "_fetch_html", return_value=menu_html(image_host="images.example.invalid")):
            menu = client.menu()
        self.assertIsNone(menu["recipes"][0]["image_url"])

    def test_recent_cache_is_returned_as_explicitly_stale_on_provider_failure(self):
        client = HelloFreshNorwayClient()
        with patch.object(client, "_fetch_html", return_value=menu_html()):
            client.menu()
        client._cached_at = time.monotonic() - CACHE_SECONDS - 1
        with patch.object(client, "_read_menu", side_effect=HelloFreshUnavailable("down")):
            stale = client.menu()
        self.assertTrue(stale["stale"])
        self.assertIn("sist hentede", stale["warning"])


if __name__ == "__main__":
    unittest.main()
