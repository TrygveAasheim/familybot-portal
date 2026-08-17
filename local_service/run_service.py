#!/usr/bin/env python3
"""Supervise the FamilyBot web, API and Bonjour advertisement as one service."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PYTHON = "/Library/Developer/CommandLineTools/usr/bin/python3"
children: list[subprocess.Popen[bytes]] = []
stopping = False


def stop(_signum: int | None = None, _frame: object | None = None) -> None:
    global stopping
    if stopping:
        return
    stopping = True
    for process in reversed(children):
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 8
    for process in reversed(children):
        remaining = max(0.1, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()


def start(command: list[str], environment: dict[str, str]) -> subprocess.Popen[bytes]:
    process = subprocess.Popen(command, cwd=ROOT, env=environment)
    children.append(process)
    return process


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    environment = os.environ.copy()
    environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    environment["NODE_ENV"] = "production"
    environment["HOST"] = "0.0.0.0"
    environment["PORT"] = "3000"
    start([
        PYTHON, str(ROOT / "local_api/familybot_api.py"), "--host", "0.0.0.0", "--lan",
        "--parent-pin-file", str(ROOT / "runtime/parent-pin.txt"),
    ], environment)
    start(["/opt/homebrew/bin/node", str(ROOT / "dist/standalone/server.js")], environment)
    start([
        "/usr/bin/dns-sd", "-R", "Familieportalen", "_http._tcp", "local", "3000",
        "path=/", "role=family-dashboard",
    ], environment)
    print("[familybot-portal] web=:3000 api=:8788 bonjour=Familieportalen", flush=True)
    try:
        while not stopping:
            for process in children:
                code = process.poll()
                if code is not None:
                    print(f"[familybot-portal] child {process.args!r} exited with {code}", file=sys.stderr, flush=True)
                    stop()
                    raise SystemExit(code or 1)
            time.sleep(1)
    finally:
        stop()


if __name__ == "__main__":
    main()
