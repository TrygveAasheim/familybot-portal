#!/usr/bin/env python3
"""Run fixture tests without inheriting a deployed household's configuration."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def test_environment(workspace: Path) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("FAMILYBOT_") and key != "OPENCLAW_WORKSPACE"}
    environment["FAMILYBOT_WORKSPACE"] = str(workspace)
    return environment


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="familybot-api-tests-") as directory:
        return subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "local_api", "-p", "test_*.py"],
            cwd=Path(__file__).resolve().parents[1],
            env=test_environment(Path(directory)), check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
