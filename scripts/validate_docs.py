#!/usr/bin/env python3
"""Validate Familieportalen's cold-start documentation contract."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote


REQUIRED_FILES = {
    "AGENTS.md",
    "README.md",
    "config/README.md",
    "docs/ACCEPTANCE_IPAD_FAMILY_DASHBOARD.md",
    "docs/BRANCHES.md",
    "docs/DATA_BOUNDARY.md",
    "docs/DEVELOPMENT_GUIDE.md",
    "docs/FEATURE_MAP.md",
    "docs/NEW_SESSION_VERIFICATION.md",
}
REQUIRED_README_LINKS = {
    "AGENTS.md",
    "docs/DEVELOPMENT_GUIDE.md",
    "docs/NEW_SESSION_VERIFICATION.md",
}
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def markdown_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.md") if ".git" not in path.parts and "node_modules" not in path.parts)


def local_link_target(document: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().strip("<>")
    if not target or target.startswith("#") or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        return None
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    return (document.parent / target).resolve() if target else None


def validate_repository(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for relative in sorted(REQUIRED_FILES):
        if not (root / relative).is_file():
            errors.append(f"missing required documentation: {relative}")

    readme = root / "README.md"
    if readme.is_file():
        content = readme.read_text(encoding="utf-8")
        for required_link in sorted(REQUIRED_README_LINKS):
            if required_link not in content:
                errors.append(f"README does not link to {required_link}")

    for document in markdown_files(root):
        content = document.read_text(encoding="utf-8")
        relative_document = document.relative_to(root)
        if content.count("```") % 2:
            errors.append(f"unbalanced fenced code block: {relative_document}")
        for raw_target in MARKDOWN_LINK.findall(content):
            target = local_link_target(document, raw_target)
            if target is not None and not target.exists():
                errors.append(f"broken local link in {relative_document}: {raw_target}")

    package_path = root / "package.json"
    if package_path.is_file():
        scripts = json.loads(package_path.read_text(encoding="utf-8")).get("scripts", {})
        if scripts.get("docs:check") != "python3 scripts/validate_docs.py":
            errors.append("package.json must expose docs:check")
    else:
        errors.append("missing package.json")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = validate_repository(args.root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Documentation validation failed with {len(errors)} error(s).")
        return 1
    count = len(markdown_files(args.root.resolve()))
    print(f"Documentation validation OK: {count} Markdown files checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
