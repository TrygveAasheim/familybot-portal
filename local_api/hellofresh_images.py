#!/usr/bin/env python3
"""Bounded local cache for reviewed public HelloFresh recipe images.

The browser receives only content-addressed local routes.  Source URLs are
registered server-side after the existing HelloFresh CDN allowlist has accepted
them; callers cannot supply an arbitrary URL to the image route.  Cached public
images remain available if the provider is temporarily unavailable.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, NamedTuple

from hellofresh_norway import _safe_image_url

IMAGE_ROUTE_PREFIX = "/api/hellofresh/images/"
IMAGE_KEY = re.compile(r"^[0-9a-f]{64}$")
MAX_IMAGE_BYTES = 6_000_000
MAX_PREFETCH_WEEKS = 8
MAX_IMAGES_PER_MENU = 120
MAX_CACHE_ENTRIES = 600
MAX_CACHE_BYTES = 256 * 1024 * 1024
CACHE_VARIANT = "w960-v1"
DEFAULT_CACHE_DIR = Path(
    os.environ.get(
        "FAMILYBOT_HELLOFRESH_IMAGE_CACHE",
        str(
            Path(
                os.environ.get(
                    "FAMILYBOT_WORKSPACE",
                    str(Path.home() / ".openclaw/workspace"),
                )
            )
            / "cache/hellofresh-images"
        ),
    )
).expanduser()
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/avif",
}


class HelloFreshImageUnavailable(RuntimeError):
    """A registered HelloFresh image is not locally available."""


class CachedImage(NamedTuple):
    body: bytes
    content_type: str
    etag: str


def _image_key(source_url: str) -> str:
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()


def _matches_image_type(content_type: str, body: bytes) -> bool:
    if content_type == "image/jpeg":
        return body.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return body.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP"
    if content_type == "image/avif":
        return len(body) >= 12 and body[4:12] in {
            b"ftypavif",
            b"ftypavis",
            b"ftypmif1",
        }
    return False


def _optimized_source_url(source_url: str) -> str:
    """Request the provider's bounded rendition without broad URL rewriting."""
    parsed = urllib.parse.urlparse(source_url)
    path = parsed.path
    if parsed.hostname == "img.hellofresh.com" and path.startswith("/q_auto/recipes/image/"):
        path = "/c_limit,f_auto,q_auto,w_960/" + path.removeprefix("/q_auto/")
    # Provider filenames can contain Norwegian characters. urllib requires an
    # ASCII request target, while percent escapes already present must survive.
    path = urllib.parse.quote(path, safe="/%:@,=+_-~")
    query = urllib.parse.quote(parsed.query, safe="=&%/:,@+._-~")
    return urllib.parse.urlunparse(parsed._replace(path=path, query=query))


class HelloFreshImageCache:
    """Register, fetch and serve only reviewed HelloFresh CDN images."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        *,
        timeout: int = 15,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.cache_dir = (cache_dir or DEFAULT_CACHE_DIR).expanduser()
        self.timeout = timeout
        self._opener = opener or urllib.request.urlopen
        self._locks_guard = threading.Lock()
        self._key_locks: dict[str, threading.Lock] = {}

    def _ensure_directory(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.cache_dir.chmod(0o700)
        except OSError:
            pass

    def _paths(self, key: str) -> tuple[Path, Path]:
        if not IMAGE_KEY.fullmatch(key):
            raise HelloFreshImageUnavailable("Ugyldig lokalt bildenøkkel.")
        return self.cache_dir / f"{key}.bin", self.cache_dir / f"{key}.json"

    def _key_lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._key_locks.setdefault(key, threading.Lock())

    @staticmethod
    def _atomic_write(path: Path, value: bytes) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            path.chmod(0o600)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _load_metadata(self, key: str) -> dict[str, Any]:
        _, metadata_path = self._paths(key)
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HelloFreshImageUnavailable("Det lokale bildet er ikke registrert.") from exc
        source_url = metadata.get("source_url") if isinstance(metadata, dict) else None
        safe_url = _safe_image_url(source_url)
        if safe_url != source_url or _image_key(source_url) != key:
            raise HelloFreshImageUnavailable("Det lokale bildet har ugyldig metadata.")
        return metadata

    def register(self, source_url: Any) -> str | None:
        """Register an allowlisted source URL and return its local route."""
        safe_url = _safe_image_url(source_url)
        if not safe_url:
            return None
        key = _image_key(safe_url)
        self._ensure_directory()
        _, metadata_path = self._paths(key)
        with self._key_lock(key):
            if not metadata_path.is_file():
                self._atomic_write(
                    metadata_path,
                    (json.dumps({"version": 1, "source_url": safe_url}, sort_keys=True) + "\n").encode("utf-8"),
                )
        return f"{IMAGE_ROUTE_PREFIX}{key}"

    def is_registered(self, key: str) -> bool:
        """Return whether a key has valid server-created source metadata."""
        try:
            self._load_metadata(key)
            return True
        except HelloFreshImageUnavailable:
            return False

    def localize_contract(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Copy a curated menu/detail contract and replace its image URLs."""
        localized = copy.deepcopy(payload)
        image_url = localized.get("image_url")
        if image_url:
            localized["image_url"] = self.register(image_url)
        recipes = localized.get("recipes")
        if isinstance(recipes, list):
            for recipe in recipes[:MAX_IMAGES_PER_MENU]:
                if isinstance(recipe, dict) and recipe.get("image_url"):
                    recipe["image_url"] = self.register(recipe["image_url"])
        return localized

    def _cached(self, key: str, metadata: dict[str, Any]) -> CachedImage | None:
        image_path, _ = self._paths(key)
        content_type = metadata.get("content_type")
        etag = metadata.get("etag")
        if (
            metadata.get("variant") != CACHE_VARIANT
            or content_type not in ALLOWED_CONTENT_TYPES
            or not isinstance(etag, str)
        ):
            return None
        try:
            if image_path.stat().st_size > MAX_IMAGE_BYTES:
                return None
            body = image_path.read_bytes()
        except OSError:
            return None
        if not body or hashlib.sha256(body).hexdigest() != etag:
            return None
        if not _matches_image_type(content_type, body):
            return None
        try:
            os.utime(image_path, None)
        except OSError:
            pass
        return CachedImage(body, content_type, etag)

    def _download(self, key: str, metadata: dict[str, Any]) -> CachedImage:
        source_url = metadata["source_url"]
        optimized_url = _optimized_source_url(source_url)
        if not _safe_image_url(optimized_url):
            raise HelloFreshImageUnavailable("HelloFresh-bildet hadde en ugyldig adresse.")
        request = urllib.request.Request(
            optimized_url,
            headers={
                "Accept": "image/webp,image/png,image/jpeg,image/avif;q=0.8",
                "User-Agent": "FamilyBot-Portal/0.1 (local HelloFresh image cache)",
            },
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                final_url = response.geturl()
                if _safe_image_url(final_url) != final_url:
                    raise HelloFreshImageUnavailable("HelloFresh-bildet ble sendt til et ukjent domene.")
                content_type = str(response.headers.get("content-type", "")).split(";", 1)[0].strip().lower()
                if content_type == "image/jpg":
                    content_type = "image/jpeg"
                if content_type not in ALLOWED_CONTENT_TYPES:
                    raise HelloFreshImageUnavailable("HelloFresh-bildet hadde et ukjent format.")
                content_length = str(response.headers.get("content-length", ""))
                if content_length.isdigit() and int(content_length) > MAX_IMAGE_BYTES:
                    raise HelloFreshImageUnavailable("HelloFresh-bildet var større enn forventet.")
                body = response.read(MAX_IMAGE_BYTES + 1)
        except HelloFreshImageUnavailable:
            raise
        except (OSError, urllib.error.URLError) as exc:
            raise HelloFreshImageUnavailable("HelloFresh-bildet svarer ikke akkurat nå.") from exc
        if not body or len(body) > MAX_IMAGE_BYTES:
            raise HelloFreshImageUnavailable("HelloFresh-bildet var større enn forventet.")
        if not _matches_image_type(content_type, body):
            raise HelloFreshImageUnavailable("HelloFresh-bildet bestod ikke formatkontrollen.")
        etag = hashlib.sha256(body).hexdigest()
        image_path, metadata_path = self._paths(key)
        self._atomic_write(image_path, body)
        stored_metadata = {
            "version": 1,
            "source_url": source_url,
            "content_type": content_type,
            "etag": etag,
            "bytes": len(body),
            "variant": CACHE_VARIANT,
            "fetched_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self._atomic_write(
            metadata_path,
            (json.dumps(stored_metadata, sort_keys=True) + "\n").encode("utf-8"),
        )
        return CachedImage(body, content_type, etag)

    def get(self, key: str, *, refresh: bool = False) -> CachedImage:
        """Return a cached image, fetching once if needed; stale beats empty."""
        with self._key_lock(key):
            metadata = self._load_metadata(key)
            cached = self._cached(key, metadata)
            if cached is not None and not refresh:
                return cached
            try:
                return self._download(key, metadata)
            except HelloFreshImageUnavailable:
                if cached is not None:
                    return cached
                raise

    def prefetch_many(self, source_urls: list[str], *, refresh: bool = False) -> dict[str, int]:
        """Fetch a bounded URL set concurrently and report counts only."""
        registered: dict[str, str] = {}
        for source_url in source_urls[: MAX_PREFETCH_WEEKS * MAX_IMAGES_PER_MENU]:
            route = self.register(source_url)
            if route:
                registered[route.rsplit("/", 1)[-1]] = source_url
        available = 0
        failed = 0
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="hellofresh-image") as executor:
            futures = {executor.submit(self.get, key, refresh=refresh): key for key in registered}
            for future in as_completed(futures):
                try:
                    future.result()
                    available += 1
                except Exception:  # noqa: BLE001 - each provider/cache failure is counted per image.
                    failed += 1
        return {"requested": len(registered), "available": available, "failed": failed}

    def prune(
        self,
        *,
        max_entries: int = MAX_CACHE_ENTRIES,
        max_bytes: int = MAX_CACHE_BYTES,
    ) -> dict[str, int]:
        """Bound disk use by least-recently-served image mtime."""
        self._ensure_directory()
        entries: list[tuple[float, int, Path, Path]] = []
        for image_path in self.cache_dir.glob("*.bin"):
            key = image_path.stem
            if not IMAGE_KEY.fullmatch(key):
                continue
            try:
                stat_result = image_path.stat()
            except OSError:
                continue
            entries.append((stat_result.st_mtime, stat_result.st_size, image_path, self.cache_dir / f"{key}.json"))
        entries.sort(reverse=True)
        kept_bytes = 0
        removed = 0
        for index, (_, size, image_path, metadata_path) in enumerate(entries):
            keep = index < max_entries and kept_bytes + size <= max_bytes
            if keep:
                kept_bytes += size
                continue
            for path in (image_path, metadata_path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            removed += 1
        return {"kept": len(entries) - removed, "bytes": kept_bytes, "removed": removed}


def prefetch_upcoming_images(account: Any, cache: HelloFreshImageCache) -> dict[str, int]:
    """Read upcoming published menus and warm their public image URLs."""
    weeks_payload = account.weeks()
    weeks = weeks_payload.get("weeks") if isinstance(weeks_payload, dict) else None
    published = [
        item.get("week")
        for item in (weeks if isinstance(weeks, list) else [])[:MAX_PREFETCH_WEEKS]
        if isinstance(item, dict) and item.get("menu_published") is True
    ]
    source_urls: list[str] = []
    menu_failures = 0
    for week in published:
        try:
            menu = account.menu(week)
        except Exception:  # noqa: BLE001 - provider errors are summarized without sensitive payloads.
            menu_failures += 1
            continue
        recipes = menu.get("recipes") if isinstance(menu, dict) else None
        for recipe in (recipes if isinstance(recipes, list) else [])[:MAX_IMAGES_PER_MENU]:
            source_url = recipe.get("image_url") if isinstance(recipe, dict) else None
            if _safe_image_url(source_url):
                source_urls.append(source_url)
    result = cache.prefetch_many(source_urls)
    result.update({"weeks": len(published), "menu_failures": menu_failures})
    result.update({f"cache_{key}": value for key, value in cache.prune().items()})
    return result
