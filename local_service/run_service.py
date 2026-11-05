#!/usr/bin/env python3
"""Supervise the FamilyBot web, API and Bonjour advertisement as one service."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "local_api"))

from family_config import portal_settings  # noqa: E402

PYTHON = sys.executable
LAN_HOST = "0.0.0.0"  # nosec B104
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
    environment["HOST"] = LAN_HOST
    workspace = Path(
        environment.get("FAMILYBOT_WORKSPACE", str(Path.home() / ".openclaw/workspace"))
    ).expanduser()
    settings = portal_settings(workspace)
    web_port = int(settings.get("web_port") or 3000)
    api_port = int(settings.get("api_port") or 8788)
    bonjour_name = str(settings.get("bonjour_name") or "Familieportalen")
    environment["PORT"] = str(web_port)
    node_binary = environment.get("FAMILYBOT_NODE") or shutil.which("node", path=environment["PATH"])
    if not node_binary:
        print("[familybot-portal] Node.js was not found; rerun scripts/deploy-local.sh", file=sys.stderr)
        raise SystemExit(78)
    start([
        PYTHON, str(ROOT / "local_api/familybot_api.py"), "--host", LAN_HOST, "--lan",
        "--port", str(api_port), "--workspace", str(workspace),
        "--parent-pin-file", str(ROOT / "runtime/parent-pin.txt"),
    ], environment)
    start([node_binary, str(ROOT / "dist/standalone/server.js")], environment)
    start([
        "/usr/bin/dns-sd", "-R", bonjour_name, "_http._tcp", "local", str(web_port),
        "path=/", "role=family-dashboard",
    ], environment)
    print(
        f"[familybot-portal] web=:{web_port} api=:{api_port} bonjour={bonjour_name}",
        flush=True,
    )
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
