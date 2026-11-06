#!/usr/bin/env python3
"""Explicit-target read-only runtime probes, never historical browser evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import stat
from pathlib import Path


def applicability(config: dict) -> dict[str, dict]:
    records = {f"AC-{n:02}": {"status": "not_run", "evidence": "Full criterion not measured by runtime probes"}
               for n in range(1, 21)}
    children = any(m.get("role") == "child" for m in config["members"])
    features = config["portal"].get("features", {})
    email = config.get("integrations", {}).get("email", {})
    enabled = {
        **{f"AC-{n:02}": children for n in (2, 3, 4, 5, 6, 7, 12, 13, 14)},
        "AC-16": children and config.get("profile", "agent") == "agent",
        "AC-17": children and bool(email) and email.get("enabled") is not False,
        "AC-18": features.get("oda") is True,
        "AC-19": features.get("hellofresh") is True,
        "AC-20": features.get("hellofresh") is True and features.get("hellofresh_account") is True,
    }
    for criterion, active in enabled.items():
        if not active:
            records[criterion] = {"status": "not_applicable", "evidence": "Capability absent for this household/profile"}
    return records


def request(host: str, port: int, path: str, origin: str, token: str = "") -> tuple[int, bytes]:
    connection = http.client.HTTPConnection(host, port, timeout=10)
    try:
        connection.request("GET", path, headers={"Origin": origin, "X-FamilyBot-Local-Token": token})
        response = connection.getresponse()
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Oversized response")
        return response.status, raw
    finally:
        connection.close()


def probe(workspace: Path, host: str, *, allow_integrations: bool = False) -> dict:
    config_path = workspace / "config/family.local.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not allow_integrations and any(
        isinstance(v, dict) and v and v.get("enabled") is not False
        for v in config.get("integrations", {}).values()
    ):
        raise ValueError("Configured integrations may make external requests; explicit consent required")
    portal = config["portal"]
    origin = f"http://{portal['hostname']}:{portal['web_port']}"
    if origin not in portal["allowed_origins"]:
        raise ValueError("Configured hostname origin is not allowlisted")
    checks = []

    def record(name: str, passed: bool) -> None:
        checks.append({"check": name, "status": "pass" if passed else "fail"})

    api_port = int(portal["api_port"])
    status, web = request(host, int(portal["web_port"]), "/", origin)
    record("web_identity", status == 200 and b"<html" in web.lower()
           and any(m in web.lower() for m in (b"familybot", b"familieportalen")))
    status, raw = request(host, api_port, "/api/health", origin)
    health = json.loads(raw)
    record("api_identity", status == 200 and health.get("ok") is True
           and health.get("service") == "familybot-dashboard-api")
    status, raw = request(host, api_port, "/api/session", origin)
    session = json.loads(raw)
    record("session_contract", status == 200 and session.get("api") == "familybot-local-v2"
           and bool(session.get("token")))
    status, raw = request(host, api_port, "/api/dashboard", origin, session.get("token", ""))
    dashboard = json.loads(raw)
    expected = {m["member_id"] for m in config["members"] if m.get("role") == "child"}
    children = dashboard.get("children", [])
    record("configured_children", status == 200 and {c["id"] for c in children} == expected)
    record("reward_contract", all(
        c.get("reward") is None or (
            all(k in c["reward"] for k in ("earned", "remaining", "percent", "target_value", "title"))
            and c["reward"]["target_value"] > 0
        ) for c in children
    ))
    foreign, _ = request(host, api_port, "/api/session", "https://invalid.example")
    unauthorized, _ = request(host, api_port, "/api/dashboard", origin)
    record("foreign_origin_rejected", foreign == 403)
    record("missing_session_rejected", unauthorized == 403)
    record("private_file_modes", all(
        stat.S_IMODE(p.stat().st_mode) == 0o600
        for p in (config_path, workspace / "config/parent-pin.txt", workspace / "db/family.db")
    ))
    configured = portal.get("features", {})
    for feature in ("oda", "oda_ai", "hellofresh", "hellofresh_account"):
        active = configured.get(feature) is True
        if feature == "oda_ai":
            active = active and configured.get("oda") is True
        if feature == "hellofresh_account":
            active = active and configured.get("hellofresh") is True
        record(f"feature_{feature}", session.get("features", {}).get(feature) is active)
    # Never contact provider routes, open credentials, or count old browser JSON.
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "evidence_class": "read-only HTTP/config probes",
        "automated_checks_ok": all(c["status"] == "pass" for c in checks),
        "release_ready": False,
        "checks": checks,
        "criteria": applicability(config),
        "outstanding": ["fresh browser/layout evidence", "physical iPad and LAN Bonjour",
                        "managed restart evidence", "enabled-provider acceptance"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="explicit isolated test workspace")
    parser.add_argument("--host", required=True, help="explicit target hostname or loopback address")
    parser.add_argument("--allow-integrations", action="store_true",
                        help="consent to dashboard-triggered configured external adapter reads")
    parser.add_argument("--require-release", action="store_true", help="fail while full release evidence is outstanding")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = probe(args.workspace.expanduser(), args.host, allow_integrations=args.allow_integrations)
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException) as exc:
        report = {"automated_checks_ok": False, "release_ready": False,
                  "error": f"Probe could not complete ({type(exc).__name__}); check explicit target/config"}
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["automated_checks_ok"] and not args.require_release else 1


if __name__ == "__main__":
    raise SystemExit(main())
