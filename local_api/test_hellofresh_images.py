import io
import os
import stat
import tempfile
import unittest
import urllib.error
from pathlib import Path

from hellofresh_images import (
    HelloFreshImageCache,
    HelloFreshImageUnavailable,
    prefetch_upcoming_images,
)

JPEG = b"\xff\xd8\xff\xe0" + b"familybot-image" * 10


class FakeResponse:
    def __init__(self, body=JPEG, *, content_type="image/jpeg", url="https://img.hellofresh.com/test/meal.jpg"):
        self._body = io.BytesIO(body)
        self.headers = {"content-type": content_type, "content-length": str(len(body))}
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return self._url

    def read(self, size=-1):
        return self._body.read(size)


class SequenceOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, request, **kwargs):
        self.calls.append((request.full_url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeAccount:
    def __init__(self):
        self.calls = []

    def weeks(self):
        return {
            "weeks": [
                {"week": "2026-W46", "menu_published": True},
                {"week": "2026-W47", "menu_published": False},
            ]
        }

    def menu(self, week):
        self.calls.append(week)
        return {
            "recipes": [
                {"image_url": "https://img.hellofresh.com/test/meal.jpg"},
                {"image_url": "https://attacker.example/unsafe.jpg"},
            ]
        }


class HelloFreshImageCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.temp.name) / "images"

    def tearDown(self):
        self.temp.cleanup()

    def test_register_fetch_and_reuse_local_image(self):
        opener = SequenceOpener(FakeResponse())
        cache = HelloFreshImageCache(self.cache_dir, opener=opener)
        route = cache.register("https://img.hellofresh.com/q_auto/recipes/image/meal.jpg")
        self.assertRegex(route or "", r"^/api/hellofresh/images/[0-9a-f]{64}$")
        key = str(route).rsplit("/", 1)[-1]
        first = cache.get(key)
        second = cache.get(key)
        self.assertEqual(first, second)
        self.assertEqual(first.content_type, "image/jpeg")
        self.assertEqual(len(opener.calls), 1)
        self.assertIn("/c_limit,f_auto,q_auto,w_960/recipes/image/", opener.calls[0][0])
        self.assertEqual(stat.S_IMODE(self.cache_dir.stat().st_mode), 0o700)
        self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in self.cache_dir.iterdir()))

    def test_provider_filename_is_percent_encoded_before_fetch(self):
        url = "https://img.hellofresh.com/q_auto/recipes/image/rød-grønnsak.jpg"
        optimized = "https://img.hellofresh.com/c_limit,f_auto,q_auto,w_960/recipes/image/r%C3%B8d-gr%C3%B8nnsak.jpg"
        opener = SequenceOpener(FakeResponse(url=optimized))
        cache = HelloFreshImageCache(self.cache_dir, opener=opener)
        route = cache.register(url)
        cache.get(str(route).rsplit("/", 1)[-1])
        self.assertEqual(opener.calls[0][0], optimized)

    def test_rejects_unreviewed_source_redirect_and_non_image_content(self):
        cache = HelloFreshImageCache(self.cache_dir, opener=SequenceOpener())
        self.assertIsNone(cache.register("https://attacker.example/image.jpg"))
        self.assertFalse(self.cache_dir.exists())

        unsafe_redirect = SequenceOpener(FakeResponse(url="https://attacker.example/image.jpg"))
        cache = HelloFreshImageCache(self.cache_dir, opener=unsafe_redirect)
        route = cache.register("https://img.hellofresh.com/test/meal.jpg")
        with self.assertRaises(HelloFreshImageUnavailable):
            cache.get(str(route).rsplit("/", 1)[-1])

        wrong_type = SequenceOpener(FakeResponse(b"<html>no</html>", content_type="text/html"))
        cache = HelloFreshImageCache(self.cache_dir, opener=wrong_type)
        other = cache.register("https://img.hellofresh.com/test/other.jpg")
        with self.assertRaises(HelloFreshImageUnavailable):
            cache.get(str(other).rsplit("/", 1)[-1])

    def test_refresh_failure_keeps_last_valid_image(self):
        opener = SequenceOpener(FakeResponse(), urllib.error.URLError("offline"))
        cache = HelloFreshImageCache(self.cache_dir, opener=opener)
        route = cache.register("https://img.hellofresh.com/test/meal.jpg")
        key = str(route).rsplit("/", 1)[-1]
        original = cache.get(key)
        stale = cache.get(key, refresh=True)
        self.assertEqual(stale, original)
        self.assertEqual(len(opener.calls), 2)

    def test_localize_contract_does_not_mutate_provider_contract(self):
        cache = HelloFreshImageCache(self.cache_dir, opener=SequenceOpener())
        source = {
            "image_url": "https://img.hellofresh.com/test/detail.jpg",
            "recipes": [{"image_url": "https://img.hellofresh.com/test/meal.jpg"}],
        }
        localized = cache.localize_contract(source)
        self.assertTrue(localized["image_url"].startswith("/api/hellofresh/images/"))
        self.assertTrue(localized["recipes"][0]["image_url"].startswith("/api/hellofresh/images/"))
        self.assertEqual(source["recipes"][0]["image_url"], "https://img.hellofresh.com/test/meal.jpg")

    def test_prefetch_reads_only_published_weeks_and_prunes_to_bounds(self):
        opener = SequenceOpener(FakeResponse())
        cache = HelloFreshImageCache(self.cache_dir, opener=opener)
        account = FakeAccount()
        result = prefetch_upcoming_images(account, cache)
        self.assertEqual(account.calls, ["2026-W46"])
        self.assertEqual(result["weeks"], 1)
        self.assertEqual(result["requested"], 1)
        self.assertEqual(result["available"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["cache_kept"], 1)

    def test_prune_removes_oldest_entries_and_metadata(self):
        opener = SequenceOpener(
            FakeResponse(url="https://img.hellofresh.com/test/one.jpg"),
            FakeResponse(url="https://img.hellofresh.com/test/two.jpg"),
        )
        cache = HelloFreshImageCache(self.cache_dir, opener=opener)
        routes = [
            cache.register("https://img.hellofresh.com/test/one.jpg"),
            cache.register("https://img.hellofresh.com/test/two.jpg"),
        ]
        for route in routes:
            cache.get(str(route).rsplit("/", 1)[-1])
        first_key = str(routes[0]).rsplit("/", 1)[-1]
        os.utime(self.cache_dir / f"{first_key}.bin", (1, 1))
        result = cache.prune(max_entries=1)
        self.assertEqual(result["removed"], 1)
        self.assertFalse((self.cache_dir / f"{first_key}.bin").exists())
        self.assertFalse((self.cache_dir / f"{first_key}.json").exists())


if __name__ == "__main__":
    unittest.main()
