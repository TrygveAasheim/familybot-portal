"""Read only the PDF registered to a plan, never a browser-supplied path."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

MAX_PDF_BYTES = 15 * 1024 * 1024


class DocumentUnavailable(ValueError):
    """No safely readable source document; callers must not expose its path."""


def read_document(workspace: Path, layout_json: str) -> bytes:
    """Open beneath the fixed attachment root, refusing symlinks and special files.

    openat/O_NOFOLLOW on every relative component closes the symlink race between
    checking a stored path and opening it. No URL or path comes from the browser.
    """
    descriptors: list[int] = []
    try:
        if len(layout_json) > 2_000_000:
            raise DocumentUnavailable()
        layout = json.loads(layout_json)
        source = layout.get("source_pdf") if isinstance(layout, dict) else None
        if not isinstance(source, str) or not source:
            raise DocumentUnavailable()
        root = workspace.resolve() / "db" / "attachments"
        path = Path(source)
        relative = path.relative_to(root)
        if not relative.parts or ".." in relative.parts or path.suffix.lower() != ".pdf":
            raise DocumentUnavailable()
        # Walk from the selected workspace as well: db/attachments cannot be links.
        descriptor = os.open(workspace.resolve(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(descriptor)
        for part in ("db", "attachments", *relative.parts[:-1]):
            descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            descriptors.append(descriptor)
        descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        descriptors.append(descriptor)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 8 <= info.st_size <= MAX_PDF_BYTES:
            raise DocumentUnavailable()
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            body = stream.read(MAX_PDF_BYTES + 1)
        if len(body) > MAX_PDF_BYTES or not re.match(rb"%PDF-[12]\.\d", body):
            raise DocumentUnavailable()
        expected = layout.get("source_sha256")
        if expected is not None and (
            not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)
            or hashlib.sha256(body).hexdigest() != expected
        ):
            raise DocumentUnavailable()
        return body
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise DocumentUnavailable("Originaldokumentet er ikke tilgjengelig.") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
