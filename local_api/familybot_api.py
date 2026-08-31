#!/usr/bin/env python3
"""Private-LAN, curated API for the FamilyBot household dashboard.

The service deliberately exposes a small view of the OpenClaw database. It
never returns raw email bodies, Telegram identifiers, Spond JSON, or secrets.
Child mutations require an in-memory session token. Parent operations also
require a PIN-backed, rate-limited parent session. Browser origins are an exact
allowlist loaded from the canonical local family configuration.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
import threading
import tempfile
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from family_config import integration, member_profiles, portal_settings


DEFAULT_WORKSPACE = Path(
    os.environ.get("FAMILYBOT_WORKSPACE", str(Path.home() / ".openclaw/workspace"))
).expanduser()
DEFAULT_DB = DEFAULT_WORKSPACE / "db/family.db"
LANES = {"todo", "inprogress", "onhold", "done"}
PRIORITIES = {"must-do", "important", "nice-to"}
REPEAT_MODES = {"once", "weekly"}
WEEKDAY_NAMES = {
    1: "mandag",
    2: "tirsdag",
    3: "onsdag",
    4: "torsdag",
    5: "fredag",
    6: "lørdag",
    7: "søndag",
}
CHORE_COLUMNS = "id,title,description,assigned_to,lane,priority,due_date,created_at,updated_at,archived_at"
PORTAL_PORT = 3000


def iso_now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def precise_iso_now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="microseconds")


def cycle_key_for_date(repeat_mode: str, value: dt.date) -> str:
    if repeat_mode == "weekly":
        return (value - dt.timedelta(days=value.weekday())).isoformat()
    return "once"


def achievement_week_key(value: dt.date) -> str:
    year, week, _ = value.isocalendar()
    return f"{year}-W{week:02d}"


def local_date_from_timestamp(value: str) -> tuple[dt.datetime, dt.date] | None:
    try:
        timestamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
        local_timestamp = timestamp.astimezone()
        return local_timestamp, local_timestamp.date()
    except (TypeError, ValueError):
        return None


def parse_weekdays(value: Any) -> list[int]:
    if isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = str(value or "").split(",")
    try:
        weekdays = sorted({int(item) for item in raw if str(item).strip()})
    except (TypeError, ValueError) as exc:
        raise ValidationError("Velg gyldige ukedager.") from exc
    if any(day not in WEEKDAY_NAMES for day in weekdays):
        raise ValidationError("Velg gyldige ukedager.")
    return weekdays


def file_timestamp(path: Path) -> str | None:
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except OSError:
        return None


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def curated_week_plan_text(value: Any) -> str:
    """Return only plan content, excluding mail transport metadata.

    Older rows may contain a compacted email followed by extracted PDF text.
    When an attachment marker exists, the marker is the hard boundary: all
    content before it is discarded. The remaining header scrub protects rows
    created by intermediate ingestion versions without weakening the rule
    that PDF content is the authoritative plan source.
    """
    text = str(value or "").strip()
    attachment = re.search(r"\[[^\]]*attachment:\s*[^\]]+\]", text, flags=re.IGNORECASE)
    if attachment:
        text = text[attachment.end():].lstrip()
    else:
        compact_header = re.search(r"\bSubject:\s*", text, flags=re.IGNORECASE)
        compact_prefix = text[:compact_header.start()] if compact_header else ""
        if compact_header and re.search(r"\b(?:From|To|Cc|Bcc|Date|Reply-To):", compact_prefix, flags=re.IGNORECASE):
            text = text[compact_header.end():].lstrip()
        text = re.sub(
            r"^\s*(?:from|to|cc|bcc|date|reply-to):[^\n]*(?:\n|$)",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"^\s*subject:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[[^\]]*attachment:[^\]]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "", text)
    text = re.sub(r"\b(?:from|to|cc|bcc|date|reply-to|subject):\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+[A-Za-z][\w .-]*\s*<\s*>", " ", text)
    text = re.sub(r"(?im)^\s*(?:from|to|cc|bcc|date|reply-to|subject):[^\n]*\n?", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def curated_week_plan_summary(value: Any) -> str:
    """Return a compact, browser-safe summary of PDF-derived plan content."""
    return re.sub(r"\s{2,}", " ", curated_week_plan_text(value)).strip()[:360]


HEALTH_LABELS = {
    "gateway": "OpenClaw-gateway",
    "database": "database",
    "email": "e-post",
    "email_pipeline": "e-postbehandling",
    "delivery_outbox": "meldingslevering",
    "scheduler": "planlagte jobber",
    "spond": "Spond",
    "telegram": "meldingskanal",
    "disk": "diskplass",
    "calendar_hygiene": "kalenderkontroll",
}


def health_summary(workspace: Path) -> dict[str, Any]:
    """Curate deterministic health state into dashboard-safe semantics.

    Only a critical gateway or database failure means FamilyBot has stopped.
    Other integration failures are reported as degraded, so a working bot is
    never presented as completely unavailable.
    """
    snapshot_path = workspace / "db/health_status.json"
    snapshot = load_json(snapshot_path)
    legacy_path = workspace / "db/health_failures.json"
    legacy = load_json(legacy_path)
    raw_results = snapshot.get("results")
    issues = []
    if isinstance(raw_results, list):
        for item in raw_results:
            if not isinstance(item, dict) or item.get("status") not in {"warn", "critical"}:
                continue
            service = str(item.get("service") or "unknown")
            issues.append({
                "service": service,
                "label": HEALTH_LABELS.get(service, service.replace("_", " ")),
                "severity": item["status"],
            })
    elif legacy:
        for service, count in legacy.items():
            if isinstance(count, (int, float)) and count > 0:
                issues.append({
                    "service": service,
                    "label": HEALTH_LABELS.get(service, service.replace("_", " ")),
                    "severity": "critical" if service in {"gateway", "database"} else "warn",
                })

    stopped = any(
        item["severity"] == "critical" and item["service"] in {"gateway", "database"}
        for item in issues
    )
    state = "stopped" if stopped else "degraded" if issues else "ok"
    return {
        "status": state,
        "ok": not stopped,
        "issues": issues,
        "checked_at": snapshot.get("checked_at") or file_timestamp(snapshot_path) or file_timestamp(legacy_path),
    }


WEATHER_LABELS = {
    "clearsky": "klart",
    "fair": "lettskyet",
    "partlycloudy": "delvis skyet",
    "cloudy": "skyet",
    "fog": "tåke",
    "lightrain": "lett regn",
    "rain": "regn",
    "heavyrain": "kraftig regn",
    "lightsnow": "lett snø",
    "snow": "snø",
    "heavysnow": "kraftig snø",
    "sleet": "sludd",
    "rainshowers": "regnbyger",
    "snowshowers": "snøbyger",
    "thunder": "torden",
}
TRANSPORT_MODES = {"metro", "bus", "tram", "rail", "water"}
WEATHER_CACHE_VERSION = 3
WEATHER_CACHE_TTL = dt.timedelta(minutes=10)
WEATHER_TZ = ZoneInfo("Europe/Oslo")

ENTUR_ENDPOINT = "https://api.entur.io/journey-planner/v3/graphql"


def weather_summary(workspace: Path) -> dict[str, Any]:
    """Return a 30-minute cached MET forecast for the configured home location."""
    cache_path = workspace / "db/dashboard_weather.json"
    cached = load_json(cache_path)
    checked = cached.get("updated_at")
    if checked and cached.get("forecast_version") == WEATHER_CACHE_VERSION:
        try:
            age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(checked.replace("Z", "+00:00"))
            if age < WEATHER_CACHE_TTL:
                return cached
        except (TypeError, ValueError):
            pass
    try:
        weather = integration(workspace, "weather")
        latitude = float(weather["home_lat"])
        longitude = float(weather["home_lon"])
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("Configured weather coordinates are outside valid ranges")
        user_agent = str(weather.get("user_agent") or "FamilyBot-local/1.0")
        endpoint = (
            "https://api.met.no/weatherapi/locationforecast/2.0/compact"
            f"?lat={latitude:.5f}&lon={longitude:.5f}"
        )
        request = urllib.request.Request(endpoint, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(request, timeout=4) as response:
            payload = json.load(response)
        series = payload["properties"]["timeseries"]
        first = series[0]["data"]
        temperature = round(float(first["instant"]["details"]["air_temperature"]))
        symbol = str(first.get("next_1_hours", {}).get("summary", {}).get("symbol_code", "cloudy")).split("_")[0]
        label = next((text for key, text in WEATHER_LABELS.items() if symbol.startswith(key)), "skiftende vær")
        precipitation = round(sum(float(item["data"].get("next_1_hours", {}).get("details", {}).get("precipitation_amount", 0)) for item in series[:6]), 1)
        weather_now = dt.datetime.now(dt.timezone.utc).astimezone(WEATHER_TZ)
        period_date = weather_period_date(series, weather_now)
        periods = weather_periods(series, weather_now)
        result = {
            "status": f"{temperature} °C · {label}",
            "temperature": temperature,
            "precipitation_6h": precipitation,
            "symbol": symbol,
            "forecast_version": WEATHER_CACHE_VERSION,
            "period_date": period_date.isoformat() if period_date else None,
            "periods": periods,
            "advice": weather_advice(series, period_date, periods),
            "updated_at": payload["properties"].get("meta", {}).get("updated_at") or iso_now(),
            "source": "MET Locationforecast",
            "stale": False,
        }
        cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(cache_path, 0o600)
        return result
    except (OSError, KeyError, TypeError, ValueError, urllib.error.URLError):
        if cached:
            cached["stale"] = True
            return cached
        return {"status": "Værvarsel er midlertidig utilgjengelig", "updated_at": None, "source": "MET Locationforecast", "stale": True}


def weather_periods(series: list[dict[str, Any]], now: dt.datetime) -> list[dict[str, Any]]:
    """Aggregate the hourly MET forecast into the three daytime bands shown in the UI."""
    target_date = weather_period_date(series, now)
    if target_date is None:
        return []
    parsed: list[tuple[dt.datetime, dict[str, Any]]] = []
    for item in series:
        try:
            timestamp = dt.datetime.fromisoformat(str(item["time"]).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
            parsed.append((timestamp.astimezone(WEATHER_TZ), item["data"]))
        except (KeyError, TypeError, ValueError):
            continue
    periods: list[dict[str, Any]] = []
    for start, end in ((8, 12), (12, 16), (16, 20)):
        rows = [(timestamp, data) for timestamp, data in parsed if timestamp.date() == target_date and start <= timestamp.hour < end]
        temperatures = [float(data["instant"]["details"]["air_temperature"]) for _, data in rows if data.get("instant", {}).get("details", {}).get("air_temperature") is not None]
        rain_values = [float(data.get("next_1_hours", {}).get("details", {}).get("precipitation_amount", 0)) for _, data in rows]
        symbols = [str(data.get("next_1_hours", {}).get("summary", {}).get("symbol_code", "")).split("_")[0] for _, data in rows]
        symbol = next((value for value in symbols if value), "cloudy")
        label = next((text for key, text in WEATHER_LABELS.items() if symbol.startswith(key)), "skiftende vær")
        periods.append({
            "label": f"{start:02d}–{end:02d}",
            "temperature_min": round(min(temperatures)) if temperatures else None,
            "temperature_max": round(max(temperatures)) if temperatures else None,
            "precipitation_mm": round(sum(rain_values), 1),
            "symbol": symbol,
            "summary": label,
        })
    return periods


def weather_period_date(series: list[dict[str, Any]], now: dt.datetime) -> dt.date | None:
    """Choose today while a daytime band remains; otherwise choose the next forecast day."""
    local_times: list[dt.datetime] = []
    for item in series:
        try:
            timestamp = dt.datetime.fromisoformat(str(item["time"]).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
            local_times.append(timestamp.astimezone(WEATHER_TZ))
        except (KeyError, TypeError, ValueError):
            continue
    dates = list(dict.fromkeys(timestamp.date() for timestamp in local_times))
    if not dates:
        return None

    def band_count(target: dt.date) -> int:
        return sum(any(timestamp.date() == target and start <= timestamp.hour < end for timestamp in local_times) for start, end in ((8, 12), (12, 16), (16, 20)))

    today = now.date()
    if today in dates and band_count(today):
        return today
    return next((candidate for candidate in dates if candidate > today and band_count(candidate) == 3), next((candidate for candidate in dates if candidate > today), dates[0]))


def weather_advice(series: list[dict[str, Any]], period_date: dt.date | None, periods: list[dict[str, Any]]) -> str:
    """Generate a short, child-focused recommendation from the displayed forecast."""
    if period_date is None or not periods:
        return "Sjekk værvarselet før dere går."
    rows: list[tuple[dt.datetime, dict[str, Any]]] = []
    for item in series:
        try:
            timestamp = dt.datetime.fromisoformat(str(item["time"]).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
            local_timestamp = timestamp.astimezone(WEATHER_TZ)
            if local_timestamp.date() == period_date:
                rows.append((local_timestamp, item["data"]))
        except (KeyError, TypeError, ValueError):
            continue
    outdoor_rows = [(timestamp, data) for timestamp, data in rows if 6 <= timestamp.hour < 19] or rows
    temperatures = [float(data["instant"]["details"]["air_temperature"]) for _, data in outdoor_rows if data.get("instant", {}).get("details", {}).get("air_temperature") is not None]
    symbols = [str(data.get("next_1_hours", {}).get("summary", {}).get("symbol_code", "")).lower() for _, data in outdoor_rows]
    rain_values = [float(data.get("next_1_hours", {}).get("details", {}).get("precipitation_amount", 0)) for _, data in outdoor_rows]
    max_wind = max((float(data.get("instant", {}).get("details", {}).get("wind_speed", 0)) for _, data in outdoor_rows), default=0)
    minimum = min(temperatures) if temperatures else min((period["temperature_min"] for period in periods if period["temperature_min"] is not None), default=None)
    total_rain = sum(rain_values) if rain_values else sum(float(period["precipitation_mm"]) for period in periods)
    peak_rain = max(rain_values, default=0)
    if any("thunder" in symbol for symbol in symbols):
        advice = "Vanntett jakke og sko; gå inn når tordenværet kommer."
    elif any("heavyrain" in symbol for symbol in symbols) or peak_rain >= 3:
        advice = "Regnjakke og vanntette sko; en tynn jakke alene er ikke nok."
    elif any(key in symbol for symbol in symbols for key in ("snow", "sleet")):
        advice = "Varmt, vanntett ytterlag og sko som tåler vintervær."
    elif total_rain > 0.5:
        advice = "Ta med regnjakke og sko som tåler regn."
    elif minimum is not None and minimum < 10:
        advice = "Kle dere lagvis for en kjølig morgen."
    elif minimum is not None and minimum < 15:
        advice = "En lett jakke kan være nyttig tidlig og sent."
    else:
        advice = "Lette klær passer; ta med et tynt lag til ettermiddagen."
    if max_wind >= 10 and "vind" not in advice.lower():
        advice += " Velg også et vindtett ytterlag."
    return advice


def transport_summary(workspace: Path) -> dict[str, Any]:
    """Return configured line/direction departures with a short local cache."""
    transport = integration(workspace, "transport")
    stop_id = str(transport.get("stop_id") or "")
    direction_quay_id = str(transport.get("direction_quay_id") or transport.get("centre_quay_id") or "")
    transport_mode = str(transport.get("transport_mode") or "metro")
    line_code = str(transport.get("line") or "")
    stop_name = str(transport.get("stop_name") or "Lokalt stopp")
    direction_label = str(transport.get("direction_label") or "Neste avgang")
    client_name = str(transport.get("client_name") or "familybot-local")
    cache_path = workspace / "db/dashboard_departures.json"
    cached = load_json(cache_path)
    checked = cached.get("updated_at")
    if checked:
        try:
            age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
            if age < dt.timedelta(seconds=25) and cached.get("stop") == stop_name:
                return cached
        except (TypeError, ValueError):
            pass

    if not stop_id or not direction_quay_id or not line_code or transport_mode not in TRANSPORT_MODES:
        return {"ok": False, "status": "Kollektivtransport er ikke konfigurert", "stop": stop_name,
                "updated_at": None, "source": "Entur Journey Planner", "stale": True, "departures": []}
    query = """
    query LocalDepartures($id: String!) {
      stopPlace(id: $id) {
        estimatedCalls(numberOfDepartures: 30, timeRange: 7200) {
          realtime
          aimedDepartureTime
          expectedDepartureTime
          destinationDisplay { frontText }
          quay { id publicCode }
          serviceJourney { journeyPattern { line { publicCode transportMode } } }
        }
      }
    }
    """
    body = json.dumps({"query": query, "variables": {"id": stop_id}}).encode("utf-8")
    request = urllib.request.Request(
        ENTUR_ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/json",
            "ET-Client-Name": client_name,
            "User-Agent": "FamilyBot-local/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            payload = json.load(response)
        calls = payload["data"]["stopPlace"]["estimatedCalls"]
        departures = []
        for call in calls:
            line = call.get("serviceJourney", {}).get("journeyPattern", {}).get("line", {})
            quay = call.get("quay") or {}
            expected = call.get("expectedDepartureTime") or call.get("aimedDepartureTime")
            if line.get("transportMode") != transport_mode or str(line.get("publicCode")) != line_code or quay.get("id") != direction_quay_id or not expected:
                continue
            departures.append({
                "expected_departure": expected,
                "aimed_departure": call.get("aimedDepartureTime"),
                "destination": call.get("destinationDisplay", {}).get("frontText") or direction_label,
                "line": line.get("publicCode") or line_code,
                "platform": quay.get("publicCode") or "",
                "realtime": bool(call.get("realtime")),
            })
        if not departures:
            raise ValueError("Entur returned no departures for the configured line and direction")
        result = {
            "ok": True,
            "status": direction_label,
            "stop": stop_name,
            "updated_at": iso_now(),
            "source": "Entur Journey Planner",
            "stale": False,
            "departures": departures[:4],
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(cache_path)
        return result
    except (OSError, KeyError, TypeError, ValueError, urllib.error.URLError):
        if cached:
            cached["stale"] = True
            return cached
        return {
            "ok": False,
            "status": "T-baneavganger er midlertidig utilgjengelige",
            "stop": stop_name,
            "updated_at": None,
            "source": "Entur Journey Planner",
            "stale": True,
            "departures": [],
        }


class ValidationError(ValueError):
    pass


def configured_origins(workspace: Path) -> set[str]:
    configured = portal_settings(workspace).get("allowed_origins", [])
    if isinstance(configured, list):
        origins = {str(origin).rstrip("/") for origin in configured if isinstance(origin, str) and origin}
        if origins:
            return origins
    return {
        "http://familie.local:3000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    }


def trusted_portal_origin(origin: str | None, allowed_origins: set[str] | None = None) -> bool:
    if not origin:
        return False
    return origin.rstrip("/") in (allowed_origins or configured_origins(DEFAULT_WORKSPACE))


class FamilyRepository:
    def __init__(self, db_path: Path, workspace: Path = DEFAULT_WORKSPACE, audit_path: Path | None = None):
        self.db_path = db_path
        self.workspace = workspace
        self.audit_path = audit_path or Path(__file__).resolve().parent.parent / "runtime/audit.jsonl"
        self._backup_done = False
        self._backup_lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def table_exists(self, connection: sqlite3.Connection, table: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None

    def backup_before_write(self) -> None:
        with self._backup_lock:
            if self._backup_done:
                return
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_dir = self.workspace / f"backups/portal-chores-{stamp}"
            backup_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self.workspace / "backups", 0o700)
            os.chmod(backup_dir, 0o700)
            target = backup_dir / "family.db"
            fd, temporary = tempfile.mkstemp(prefix=".family-", suffix=".db", dir=backup_dir)
            os.close(fd)
            temporary_path = Path(temporary)
            source = sqlite3.connect(self.db_path)
            destination = sqlite3.connect(temporary_path)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, target)
            os.chmod(target, 0o600)
            self._backup_done = True

    def audit(self, action: str, details: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.audit_path.parent, 0o700)
        record = {"at": iso_now(), "action": action, **details}
        with self.audit_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        try:
            os.chmod(self.audit_path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
        return [dict(row) for row in cursor.fetchall()]

    def _launchd_state(self, label: str) -> dict[str, Any]:
        try:
            result = subprocess.run(
                ["launchctl", "list", label], capture_output=True, text=True, timeout=2, check=False
            )
            if result.returncode != 0:
                return {"loaded": False, "running": False, "last_exit": None}
            pid = re.search(r'"PID"\s*=\s*(\d+)', result.stdout)
            exit_status = re.search(r'"LastExitStatus"\s*=\s*(-?\d+)', result.stdout)
            return {
                "loaded": True,
                "running": bool(pid),
                "last_exit": int(exit_status.group(1)) if exit_status else None,
            }
        except (OSError, subprocess.TimeoutExpired):
            return {"loaded": False, "running": False, "last_exit": None}

    def chore_view(self, connection: sqlite3.Connection, row: sqlite3.Row, member_id: int, today: dt.date) -> dict[str, Any]:
        result = dict(row)
        mode = result.get("repeat_mode") or "once"
        weekdays = parse_weekdays(result.get("repeat_weekdays")) if mode == "weekly" else []
        target = int(result.get("repeat_target") or (len(weekdays) if weekdays else 1))
        result.update({
            "repeat_mode": mode,
            "repeat_weekdays": weekdays,
            "repeat_target": target,
            "repeat_completed": 0,
            "repeat_percent": 0,
            "repeat_status": "open",
            "available_today": True,
        })
        if mode != "weekly":
            return result
        key = cycle_key_for_date(mode, today)
        cycle = connection.execute(
            """SELECT id,status,required_count,completed_count
               FROM chore_cycles WHERE card_id=? AND member_id=? AND cycle_key=?""",
            (result["id"], member_id, key),
        ).fetchone()
        completed = connection.execute(
            """SELECT COUNT(*) FROM chore_completions
               WHERE card_id=? AND member_id=? AND cycle_id=(
                   SELECT id FROM chore_cycles WHERE card_id=? AND member_id=? AND cycle_key=?
               ) AND status != 'rejected'""",
            (result["id"], member_id, result["id"], member_id, key),
        ).fetchone()[0]
        status = cycle["status"] if cycle else "open"
        required = int(cycle["required_count"] if cycle else target)
        result.update({
            "repeat_target": required,
            "repeat_completed": int(completed),
            "repeat_percent": min(100, round(int(completed) * 100 / required)),
            "repeat_status": status,
            "available_today": today.isoweekday() in weekdays and status == "open" and not connection.execute(
                """SELECT 1 FROM chore_completions c JOIN chore_cycles x ON x.id=c.cycle_id
                   WHERE c.card_id=? AND c.member_id=? AND x.cycle_key=?
                     AND c.occurrence_date=? AND c.status != 'rejected'""",
                (result["id"], member_id, key, today.isoformat()),
            ).fetchone(),
        })
        return result

    def _weekly_cycle(self, connection: sqlite3.Connection, member_id: int) -> sqlite3.Row:
        cycle = connection.execute(
            """SELECT id,member_id,target_points,started_at,ended_at
               FROM weekly_achievement_cycles WHERE member_id=? AND ended_at IS NULL""",
            (member_id,),
        ).fetchone()
        if cycle:
            return cycle
        now = precise_iso_now()
        cursor = connection.execute(
            """INSERT INTO weekly_achievement_cycles(member_id,target_points,started_at)
               VALUES(?,30,?)""",
            (member_id, now),
        )
        return connection.execute(
            """SELECT id,member_id,target_points,started_at,ended_at
               FROM weekly_achievement_cycles WHERE id=?""",
            (cursor.lastrowid,),
        ).fetchone()

    def weekly_achievement_snapshot(self, connection: sqlite3.Connection, member_id: int, today: dt.date) -> dict[str, Any]:
        cycle = self._weekly_cycle(connection, member_id)
        target = int(cycle["target_points"])
        started = local_date_from_timestamp(cycle["started_at"])
        started_at = started[0] if started else None
        total_points = 0
        if started_at:
            rows = connection.execute(
                """SELECT points,completed_at FROM chore_completions
                   WHERE member_id=? AND status IN ('awarded','pending') AND points>0""",
                (member_id,),
            ).fetchall()
            for row in rows:
                parsed = local_date_from_timestamp(row["completed_at"])
                if not parsed or parsed[0] < started_at:
                    continue
                total_points += int(row["points"])
        full_tabs, current_points = divmod(total_points, target)
        levels = self._rows(connection.execute(
            """SELECT id,threshold_weeks,title,emoji
               FROM weekly_surprise_levels
               WHERE member_id=? AND active=1
               ORDER BY threshold_weeks,id""",
            (member_id,),
        ))
        ready = [level for level in levels if int(level["threshold_weeks"]) <= full_tabs]
        next_level = next((level for level in levels if int(level["threshold_weeks"]) > full_tabs), None)
        redemptions = self._rows(connection.execute(
            """SELECT id,full_weeks,threshold_weeks,title,created_at
               FROM weekly_achievement_redemptions
               WHERE member_id=? ORDER BY created_at DESC,id DESC LIMIT 10""",
            (member_id,),
        ))
        current_week = achievement_week_key(today)
        return {
            "target_points": target,
            "current_week": current_week,
            "current_points": current_points,
            "current_percent": min(100, round(current_points * 100 / target)),
            "total_points": total_points,
            "full_tabs": full_tabs,
            # Compatibility alias for older portal clients.
            "full_weeks": full_tabs,
            "surprises": levels,
            "ready_surprises": ready,
            "next_surprise": next_level,
            "redemptions": [
                {**item, "full_tabs": item["full_weeks"]} for item in redemptions
            ],
        }

    def dashboard(self, today: dt.date | None = None) -> dict[str, Any]:
        today = today or dt.date.today()
        annual_summary_year = today.year - 1 if today.month == 1 else None
        annual_chore_counts: dict[int, int] = {}
        monday = today + dt.timedelta(days=(7 - today.weekday()) % 7)
        if monday == today and today.weekday() != 0:
            monday += dt.timedelta(days=7)
        target_year, target_week, _ = monday.isocalendar()
        end = today + dt.timedelta(days=14)

        with self.connect() as connection:
            members = self._rows(connection.execute(
                "SELECT id, name, role, grade, school, teacher FROM family_members ORDER BY id"
            ))
            events = self._rows(connection.execute(
                """SELECT e.id, e.title, e.event_date, e.event_time, e.end_date, e.location,
                          e.bring, e.requires_response, e.response_deadline, e.source,
                          m.id AS member_id, m.name AS member
                   FROM calendar_events e LEFT JOIN family_members m ON m.id=e.member_id
                   WHERE e.event_date BETWEEN ? AND ? ORDER BY e.event_date, e.event_time, e.title""",
                (today.isoformat(), end.isoformat()),
            ))
            spond = self._rows(connection.execute(
                """SELECT s.id, s.title, s.event_date, s.event_end, s.location,
                          s.requires_response, s.rsvp_deadline, s.my_rsvp, m.id AS member_id, m.name AS member
                   FROM spond_events s LEFT JOIN family_members m ON m.id=s.member_id
                   WHERE substr(s.event_date,1,10) BETWEEN ? AND ?
                   ORDER BY s.event_date, s.title LIMIT 30""",
                (today.isoformat(), end.isoformat()),
            ))
            activities = self._rows(connection.execute(
                """SELECT a.id, a.name, a.location, a.schedule, a.paused_until, m.id AS member_id, m.name AS member
                   FROM activities a LEFT JOIN family_members m ON m.id=a.member_id
                   WHERE a.active=1 ORDER BY m.id, a.name"""
            ))
            chores = self._rows(connection.execute(
                """SELECT id, title, description, assigned_to, lane, priority, due_date, created_at, updated_at
                   FROM kanban_cards k
                   WHERE k.archived_at IS NULL
                     AND NOT EXISTS (SELECT 1 FROM family_chore_meta m WHERE m.card_id=k.id)
                   ORDER BY CASE lane WHEN 'inprogress' THEN 0 WHEN 'todo' THEN 1 ELSE 2 END,
                            CASE priority WHEN 'must-do' THEN 0 WHEN 'important' THEN 1 ELSE 2 END,
                            COALESCE(due_date,'9999-12-31'), id"""
            ))
            def plans_for(year: int, week: int) -> list[dict[str, Any]]:
                return self._rows(connection.execute(
                    """SELECT w.id, w.member_id, w.week_number, w.year,
                              substr(COALESCE(w.summary,''),1,360) AS summary,
                              w.teacher, w.created_at, m.name AS member,
                              i.structured_json AS interpretation_json
                       FROM week_plans w JOIN family_members m ON m.id=w.member_id
                       LEFT JOIN week_plan_interpretations i
                         ON i.week_plan_id=w.id AND i.status='accepted'
                       WHERE w.year=? AND w.week_number=? ORDER BY m.id, w.created_at DESC""",
                    (year, week),
                ))

            target_plans = plans_for(target_year, target_week)
            fallback_year, fallback_week, _ = (monday - dt.timedelta(days=7)).isocalendar()
            fallback_plans = plans_for(fallback_year, fallback_week)
            selected_by_member: dict[int, dict[str, Any]] = {}
            for plan in target_plans + fallback_plans:
                selected_by_member.setdefault(int(plan["member_id"]), plan)
            plans = sorted(selected_by_member.values(), key=lambda item: (item["member_id"], -int(item["id"])))
            plan_year, plan_week = target_year, target_week
            if plans and all((plan["year"], plan["week_number"]) == (fallback_year, fallback_week) for plan in plans):
                plan_year, plan_week = fallback_year, fallback_week
            for plan in plans:
                interpretation_json = plan.pop("interpretation_json", None)
                plan["interpretation"] = None
                if interpretation_json:
                    try:
                        interpretation = json.loads(interpretation_json)
                    except (TypeError, ValueError):
                        interpretation = None
                    if isinstance(interpretation, dict) and interpretation.get("version") in {1, 2}:
                        plan["interpretation"] = interpretation
                plan["summary"] = curated_week_plan_summary(plan.get("summary"))
                plan["fallback"] = (plan["year"], plan["week_number"]) != (target_year, target_week)
            plan_ids = [int(plan["id"]) for plan in plans]
            plan_days = []
            if plan_ids:
                placeholders = ",".join("?" for _ in plan_ids)
                plan_days = self._rows(connection.execute(
                    f"""SELECT d.id,d.week_plan_id,d.day,d.date,d.subject,d.note,d.homework,d.bring,
                              m.id AS member_id, m.name AS member
                       FROM week_plan_days d
                       JOIN week_plans w ON w.id=d.week_plan_id
                       JOIN family_members m ON m.id=w.member_id
                       WHERE w.id IN ({placeholders})
                       ORDER BY COALESCE(d.date,'9999-12-31'),d.id""",
                    plan_ids,
                ))
            unlinked_plan_rows = self._rows(connection.execute(
                """SELECT id, subject, received_at, processed_at, summary
                   FROM email_log
                   WHERE member_id IS NULL
                     AND lower(COALESCE(subject,'')) LIKE '%ukeplan%'
                     AND received_at>=?
                   ORDER BY received_at DESC LIMIT 12""",
                ((today - dt.timedelta(days=21)).isoformat(),),
            ))
            email_overview = dict(connection.execute(
                """SELECT COUNT(*) AS total, MAX(received_at) AS latest_received,
                          MAX(processed_at) AS latest_processed,
                          SUM(CASE WHEN processed_at IS NULL THEN 1 ELSE 0 END) AS waiting
                   FROM email_log"""
            ).fetchone())
            email_categories = self._rows(connection.execute(
                """SELECT COALESCE(category,'ukjent') AS category, COUNT(*) AS count
                   FROM email_log GROUP BY category ORDER BY count DESC"""
            ))
            school = self._rows(connection.execute(
                """SELECT id, event_type, name, start_date, end_date, year_label
                   FROM school_calendar WHERE end_date>=? ORDER BY start_date LIMIT 8""",
                (today.isoformat(),),
            ))
            hardening = {
                "delivery_outbox": self.table_exists(connection, "delivery_outbox"),
                "email_processing_state": self.table_exists(connection, "email_processing_state"),
            }
            child_chores = self._rows(connection.execute(
                """SELECT k.id,k.title,k.description,k.assigned_to,k.lane,k.due_date,
                          m.icon,m.points,m.requires_approval,m.repeat_mode,m.repeat_weekdays,m.repeat_target
                   FROM kanban_cards k JOIN family_chore_meta m ON m.card_id=k.id
                   WHERE k.archived_at IS NULL AND m.visible_to_kids=1
                     AND (k.lane IN ('todo','inprogress') OR m.repeat_mode='weekly')
                   ORDER BY CASE k.priority WHEN 'must-do' THEN 0 WHEN 'important' THEN 1 ELSE 2 END,
                            COALESCE(k.due_date,'9999-12-31'),k.id"""
            )) if self.table_exists(connection, "family_chore_meta") else []
            histories = self._rows(connection.execute(
                """SELECT c.id,c.card_id,c.member_id,c.status,c.points,c.completed_at,
                          k.title,m.icon,f.name AS member,
                          x.id AS cycle_id,x.status AS cycle_status,
                          x.completed_count AS cycle_completed,x.required_count AS cycle_required,x.points AS cycle_points,
                          CASE WHEN c.status IN ('pending','awarded') THEN 1 ELSE 0 END AS reviewable
                   FROM chore_completions c
                   JOIN kanban_cards k ON k.id=c.card_id
                   JOIN family_chore_meta m ON m.card_id=k.id AND m.visible_to_kids=1
                   JOIN family_members f ON f.id=c.member_id
                   LEFT JOIN chore_cycles x ON x.id=c.cycle_id
                   ORDER BY c.completed_at DESC,c.id DESC LIMIT 40"""
            )) if self.table_exists(connection, "chore_completions") else []
            if annual_summary_year is not None and self.table_exists(connection, "chore_completions"):
                annual_rows = connection.execute(
                    """SELECT c.member_id,c.completed_at,c.status
                       FROM chore_completions c
                       JOIN family_members f ON f.id=c.member_id AND f.role='child'
                       WHERE c.status IN ('pending','awarded')"""
                ).fetchall()
                for row in annual_rows:
                    parsed = local_date_from_timestamp(row["completed_at"])
                    if parsed and parsed[1].year == annual_summary_year:
                        annual_chore_counts[row["member_id"]] = annual_chore_counts.get(row["member_id"], 0) + 1
            goals = self._rows(connection.execute(
                """SELECT g.id,g.member_id,g.title,g.emoji,g.goal_type,g.target_value,g.unit_label,g.created_at,
                          f.name AS member,
                          COALESCE((SELECT SUM(c.points) FROM chore_completions c
                                    WHERE c.member_id=g.member_id AND c.status IN ('awarded','pending')
                                      AND c.completed_at>=g.created_at),0) AS earned
                   FROM reward_goals g JOIN family_members f ON f.id=g.member_id
                   WHERE g.active=1 ORDER BY f.id"""
            )) if self.table_exists(connection, "reward_goals") else []
            chore_views_by_member = {}
            for child in members:
                if child["role"] != "child":
                    continue
                views = []
                for item in child_chores:
                    if item["assigned_to"].lower() != child["name"].lower():
                        continue
                    view = self.chore_view(connection, item, child["id"], today)
                    if view["repeat_mode"] == "weekly" and view["repeat_status"] == "awarded":
                        continue
                    views.append(view)
                chore_views_by_member[child["id"]] = views

        spond_state = load_json(self.workspace / "db/spond_sync_state.json")
        vacation = load_json(self.workspace / "memory/vacation-mode.json")
        evidence = {
            "familybot.email": email_overview.get("latest_processed"),
            "familybot.spond": spond_state.get("checked_at"),
            "familybot.health": file_timestamp(self.workspace / "db/health_status.json")
                                or file_timestamp(self.workspace / "db/health_failures.json"),
            "familybot.status": file_timestamp(self.workspace / "STATUS.md"),
            "familybot.tbane": file_timestamp(self.workspace / "db/tbane_alert_state.json"),
            "familybot.briefing.weekday": file_timestamp(self.workspace / "logs/briefing.log"),
            "familybot.briefing.weekend": file_timestamp(self.workspace / "logs/briefing.log"),
            "familybot.briefing.weekly": file_timestamp(self.workspace / "logs/briefing.log"),
        }
        process_specs = [
            ("E-post", "familybot.email", "Hvert 15. minutt"),
            ("Spond", "familybot.spond", "Hver time"),
            ("Helsesjekk", "familybot.health", "Hvert 30. minutt"),
            ("Driftsstatus", "familybot.status", "Hvert 30. minutt"),
            ("T-bane", "familybot.tbane", "Hvert 15. minutt"),
            ("Morgenmelding", "familybot.briefing.weekday", "Hverdager 06:45"),
            ("Helgemelding", "familybot.briefing.weekend", "Helg 08:00"),
            ("Ukemelding", "familybot.briefing.weekly", "Søndag 21:00"),
        ]
        processes = []
        for name, label, schedule in process_specs:
            state = self._launchd_state(label)
            processes.append({"name": name, "label": label, "schedule": schedule, "last_seen": evidence[label], **state})

        children = [member for member in members if member["role"] == "child"]
        child_names = {member["name"] for member in children}
        planned_ids = {int(plan["member_id"]) for plan in plans}
        unlinked_plans = []
        candidate_names: set[str] = set()
        for message in unlinked_plan_rows:
            searchable = f"{message.get('subject') or ''} {message.get('summary') or ''}".lower()
            matches = []
            for child in children:
                grade = child.get("grade")
                if grade and re.search(rf"(?:^|\D){grade}\s*(?:a|\.|\.\s*trinn|trinn)(?:\D|$)", searchable):
                    matches.append(child["name"])
            candidate = matches[0] if len(matches) == 1 else None
            if candidate:
                candidate_names.add(candidate)
            unlinked_plans.append({
                "id": message["id"],
                "subject": message["subject"],
                "received_at": message["received_at"],
                "processed_at": message["processed_at"],
                "candidate_member": candidate,
                "status": "processed_not_registered",
            })
        week_plan_status = [
            {"member_id": child["id"], "member": child["name"], "received": child["id"] in planned_ids,
             "fallback": any(plan["member_id"] == child["id"] and (plan["year"], plan["week_number"]) != (target_year, target_week) for plan in plans),
             "inbox_candidate": child["name"] in candidate_names}
            for child in sorted(children, key=lambda item: item["id"])
        ]

        configured_profiles = member_profiles(self.workspace)
        annual_chore_summary = None
        if annual_summary_year is not None:
            annual_chore_summary = {
                "year": annual_summary_year,
                "children": [
                    {
                        "id": child["id"],
                        "name": configured_profiles.get(child["id"], {}).get("name") or child["name"],
                        "count": annual_chore_counts.get(child["id"], 0),
                    }
                    for child in children
                ],
            }
        dashboard_children = []
        for child in children:
            name = child["name"]
            profile = configured_profiles.get(child["id"], {})
            matching_goal = next((item for item in goals if item["member_id"] == child["id"]), None)
            weekly_achievement = self.weekly_achievement_snapshot(connection, child["id"], today)
            if matching_goal:
                earned = int(matching_goal["earned"] or 0)
                target = int(matching_goal["target_value"])
                matching_goal.update({
                    "earned": earned,
                    "remaining": max(0, target - earned),
                    "percent": min(100, round(earned * 100 / target)),
                })
            dashboard_children.append({
                "id": child["id"],
                "name": profile.get("name") or name,
                "avatar": profile.get("avatar") or "✨",
                "grade": profile.get("grade", child.get("grade")),
                "chores": chore_views_by_member.get(child["id"], []),
                "history": [item for item in histories if item["member_id"] == child["id"]][:10],
                "reward": matching_goal,
                "weekly_achievement": weekly_achievement,
            })

        week_plan_week = {
            "week": plan_week,
            "year": plan_year,
            "fallback": any((plan["year"], plan["week_number"]) != (target_year, target_week) for plan in plans),
        }
        if any((plan["year"], plan["week_number"]) == (target_year, target_week) for plan in plans) and week_plan_week["fallback"]:
            week_plan_week["mixed"] = True
        return {
            "generated_at": iso_now(),
            "date": today.isoformat(),
            "annual_chore_summary": annual_chore_summary,
            "target_week": {"week": target_week, "year": target_year, "starts": monday.isoformat()},
            "week_plan_week": week_plan_week,
            "members": members,
            "events": events,
            "spond_events": spond,
            "activities": activities,
            "chores": chores,
            "week_plans": plans,
            "week_plan_days": plan_days,
            "week_plan_status": week_plan_status,
            "unlinked_week_plan_messages": unlinked_plans,
            "school_calendar": school,
            "sources": {
                "email": {**email_overview, "categories": email_categories},
                "spond": {
                    "checked_at": spond_state.get("checked_at"),
                    "ok": spond_state.get("ok"),
                    "failures": len(spond_state.get("failures", [])),
                    "new": spond_state.get("new", 0),
                    "changed": spond_state.get("changed", 0),
                },
                "health": health_summary(self.workspace),
            },
            "vacation_mode": bool(vacation.get("enabled", False)),
            "hardening": hardening,
            "processes": processes,
            "children": dashboard_children,
            "approval_queue": [item for item in histories if item["reviewable"] and item["status"] == "pending" and item.get("cycle_status") in {None, "open", "pending"}],
            # Approved completions remain in each child's history and in the
            # database, but leave the parent's actionable review queue.
            "review_queue": [item for item in histories if item["reviewable"] and item["status"] == "pending" and item.get("cycle_status") in {None, "open", "pending"}][:20],
            "transport": transport_summary(self.workspace),
            "weather": weather_summary(self.workspace),
        }

    def week_plan_detail(self, child_id: int, plan_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            plan = connection.execute(
                """SELECT w.id,w.member_id,w.week_number,w.year,w.summary,w.raw_text,
                          m.name AS member, i.structured_json AS interpretation_json
                   FROM week_plans w JOIN family_members m ON m.id=w.member_id
                   LEFT JOIN week_plan_interpretations i
                     ON i.week_plan_id=w.id AND i.status='accepted'
                   WHERE w.id=? AND w.member_id=? AND m.role='child'""",
                (plan_id, child_id),
            ).fetchone()
            if not plan:
                raise KeyError(plan_id)
            result = dict(plan)
            interpretation_json = result.pop("interpretation_json", None)
            result["full_text"] = curated_week_plan_text(result.pop("raw_text") or result.get("summary") or "")
            result["interpretation"] = None
            if interpretation_json:
                try:
                    interpretation = json.loads(interpretation_json)
                except (TypeError, ValueError):
                    interpretation = None
                if isinstance(interpretation, dict) and interpretation.get("version") in {1, 2}:
                    result["interpretation"] = interpretation
            result["days"] = self._rows(connection.execute(
                """SELECT id,week_plan_id,day,date,subject,note,homework,bring
                   FROM week_plan_days WHERE week_plan_id=?
                   ORDER BY COALESCE(date,'9999-12-31'),id""",
                (plan_id,),
            ))
            return result

    @staticmethod
    def validate_chore(payload: dict[str, Any], partial: bool = False) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        if not partial or "title" in payload:
            title = str(payload.get("title", "")).strip()
            if not 1 <= len(title) <= 160:
                raise ValidationError("Tittel må være mellom 1 og 160 tegn.")
            clean["title"] = title
        if "description" in payload:
            description = str(payload.get("description") or "").strip()
            if len(description) > 1000:
                raise ValidationError("Beskrivelsen kan være maks 1000 tegn.")
            clean["description"] = description or None
        if not partial or "assigned_to" in payload:
            assigned = str(payload.get("assigned_to", "both")).lower()
            if not 1 <= len(assigned) <= 80 or not re.fullmatch(r"[\w .'-]+", assigned, re.UNICODE):
                raise ValidationError("Ukjent person.")
            clean["assigned_to"] = assigned
        if not partial or "priority" in payload:
            priority = str(payload.get("priority", "nice-to"))
            if priority not in PRIORITIES:
                raise ValidationError("Ukjent prioritet.")
            clean["priority"] = priority
        if "lane" in payload:
            lane = str(payload["lane"])
            if lane not in LANES:
                raise ValidationError("Ukjent status.")
            clean["lane"] = lane
        if "due_date" in payload:
            due = str(payload.get("due_date") or "").strip()
            if due:
                try:
                    dt.date.fromisoformat(due)
                except ValueError as exc:
                    raise ValidationError("Fristen må være en gyldig dato.") from exc
            clean["due_date"] = due or None
        return clean

    def create_chore(self, payload: dict[str, Any]) -> dict[str, Any]:
        values = self.validate_chore(payload)
        self.backup_before_write()
        with self.connect() as connection:
            if values["assigned_to"] != "both" and not connection.execute(
                "SELECT 1 FROM family_members WHERE lower(name)=?", (values["assigned_to"],)
            ).fetchone():
                raise ValidationError("Ukjent person.")
            cursor = connection.execute(
                """INSERT INTO kanban_cards(title,description,assigned_to,lane,priority,due_date)
                   VALUES(?,?,?,'todo',?,?)""",
                (values["title"], values.get("description"), values["assigned_to"], values["priority"], values.get("due_date")),
            )
            row = dict(connection.execute(f"SELECT {CHORE_COLUMNS} FROM kanban_cards WHERE id=?", (cursor.lastrowid,)).fetchone())
        self.audit("chore.created", {"id": row["id"], "title": row["title"]})
        return row

    def update_chore(self, chore_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        values = self.validate_chore(payload, partial=True)
        if not values:
            raise ValidationError("Ingen gyldige endringer.")
        self.backup_before_write()
        assignments = ", ".join(f"{key}=?" for key in values)
        with self.connect() as connection:
            assigned = values.get("assigned_to")
            if assigned and assigned != "both" and not connection.execute(
                "SELECT 1 FROM family_members WHERE lower(name)=?", (assigned,)
            ).fetchone():
                raise ValidationError("Ukjent person.")
            cursor = connection.execute(
                f"UPDATE kanban_cards SET {assignments}, updated_at=datetime('now') WHERE id=? AND archived_at IS NULL",
                (*values.values(), chore_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(chore_id)
            row = dict(connection.execute(f"SELECT {CHORE_COLUMNS} FROM kanban_cards WHERE id=?", (chore_id,)).fetchone())
        self.audit("chore.updated", {"id": chore_id, "fields": sorted(values)})
        return row

    def archive_chore(self, chore_id: int) -> dict[str, Any]:
        self.backup_before_write()
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE kanban_cards SET archived_at=datetime('now'), updated_at=datetime('now') WHERE id=? AND archived_at IS NULL",
                (chore_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(chore_id)
            row = dict(connection.execute(f"SELECT {CHORE_COLUMNS} FROM kanban_cards WHERE id=?", (chore_id,)).fetchone())
        self.audit("chore.archived", {"id": chore_id, "title": row["title"]})
        return row

    def restore_chore(self, chore_id: int) -> dict[str, Any]:
        self.backup_before_write()
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE kanban_cards SET archived_at=NULL, updated_at=datetime('now') WHERE id=? AND archived_at IS NOT NULL",
                (chore_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(chore_id)
            row = dict(connection.execute(f"SELECT {CHORE_COLUMNS} FROM kanban_cards WHERE id=?", (chore_id,)).fetchone())
        self.audit("chore.restored", {"id": chore_id})
        return row

    @staticmethod
    def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{label} må være et tall.") from exc
        if not minimum <= number <= maximum:
            raise ValidationError(f"{label} må være mellom {minimum} og {maximum}.")
        return number

    def normalize_child_chore(self, payload: dict[str, Any]) -> dict[str, Any]:
        assigned = str(payload.get("assigned_to", "")).lower()
        with self.connect() as connection:
            child = connection.execute(
                "SELECT id,name FROM family_members WHERE lower(name)=? AND role='child'", (assigned,)
            ).fetchone()
        if not child:
            raise ValidationError("Gjøremålet må tildeles et barn.")
        icon = str(payload.get("icon") or "✨").strip()
        if not 1 <= len(icon) <= 12:
            raise ValidationError("Velg ett kort ikon.")
        points = self._integer(payload.get("points", 1), "Poeng", 0, 1000)
        repeat_mode = str(payload.get("repeat_mode") or "once")
        if repeat_mode not in REPEAT_MODES:
            raise ValidationError("Ukjent gjentakelse.")
        repeat_weekdays = parse_weekdays(payload.get("repeat_weekdays")) if repeat_mode == "weekly" else []
        if repeat_mode == "weekly" and not repeat_weekdays:
            raise ValidationError("Velg minst én ukedag.")
        repeat_target = len(repeat_weekdays) if repeat_mode == "weekly" else 1
        base = {
            "title": payload.get("title"),
            "description": payload.get("description"),
            "assigned_to": assigned,
            "priority": payload.get("priority", "nice-to"),
            "due_date": payload.get("due_date"),
        }
        values = self.validate_chore(base)
        return {
            **values,
            "icon": icon,
            "points": points,
            "requires_approval": bool(payload.get("requires_approval")),
            "repeat_mode": repeat_mode,
            "repeat_weekdays": repeat_weekdays,
            "repeat_target": repeat_target,
        }

    def create_child_chore(
        self,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        source: str = "dashboard",
    ) -> dict[str, Any]:
        values = self.normalize_child_chore(payload)
        key = str(idempotency_key or "").strip() or None
        if key and len(key) > 200:
            raise ValidationError("Ugyldig opprettingsnøkkel.")
        self.backup_before_write()
        with self.connect() as connection:
            if key:
                existing = connection.execute(
                    "SELECT result_json FROM child_chore_operations WHERE idempotency_key=?", (key,)
                ).fetchone()
                if existing:
                    result = json.loads(existing[0])
                    result["duplicate"] = True
                    return result
            cursor = connection.execute(
                """INSERT INTO kanban_cards(title,description,assigned_to,lane,priority,due_date)
                   VALUES(?,?,?,'todo',?,?)""",
                (values["title"], values.get("description"), values["assigned_to"], values["priority"], values.get("due_date")),
            )
            connection.execute(
                """INSERT INTO family_chore_meta(
                       card_id,icon,points,requires_approval,repeat_mode,repeat_weekdays,repeat_target
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    cursor.lastrowid,
                    values["icon"],
                    values["points"],
                    int(values["requires_approval"]),
                    values["repeat_mode"],
                    ",".join(str(day) for day in values["repeat_weekdays"]),
                    values["repeat_target"],
                ),
            )
            row = dict(connection.execute(
                """SELECT k.id,k.title,k.assigned_to,k.lane,m.icon,m.points,m.requires_approval,
                          m.repeat_mode,m.repeat_weekdays,m.repeat_target
                   FROM kanban_cards k JOIN family_chore_meta m ON m.card_id=k.id WHERE k.id=?""",
                (cursor.lastrowid,),
            ).fetchone())
            row["repeat_weekdays"] = values["repeat_weekdays"]
            row["duplicate"] = False
            if key:
                connection.execute(
                    "INSERT INTO child_chore_operations(idempotency_key,result_json,source) VALUES(?,?,?)",
                    (key, json.dumps(row, ensure_ascii=False, sort_keys=True), source),
                )
        self.audit("child_chore.created", {"id": row["id"], "assigned_to": values["assigned_to"], "points": values["points"], "source": source})
        return row

    def _cycle_for_completion(
        self,
        connection: sqlite3.Connection,
        chore_id: int,
        member_id: int,
        repeat_mode: str,
        repeat_weekdays: list[int],
        repeat_target: int,
        points: int,
        today: dt.date,
    ) -> sqlite3.Row:
        if repeat_mode == "weekly" and today.isoweekday() not in repeat_weekdays:
            days = ", ".join(WEEKDAY_NAMES[day] for day in repeat_weekdays)
            raise ValidationError(f"Dette oppdraget kan gjøres {days}.")
        key = cycle_key_for_date(repeat_mode, today)
        cycle = connection.execute(
            """SELECT id,card_id,member_id,cycle_key,required_count,completed_count,status,points,created_at,decided_at
               FROM chore_cycles WHERE card_id=? AND member_id=? AND cycle_key=?""",
            (chore_id, member_id, key),
        ).fetchone()
        if cycle:
            return cycle
        cursor = connection.execute(
            """INSERT INTO chore_cycles(card_id,member_id,cycle_key,required_count,points,created_at)
               VALUES(?,?,?,?,?,?)""",
            (chore_id, member_id, key, repeat_target, points, iso_now()),
        )
        return connection.execute(
            """SELECT id,card_id,member_id,cycle_key,required_count,completed_count,status,points,created_at,decided_at
               FROM chore_cycles WHERE id=?""",
            (cursor.lastrowid,),
        ).fetchone()

    def complete_chore(self, chore_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        member_id = self._integer(payload.get("member_id"), "Barn", 1, 1000000)
        key = str(payload.get("idempotency_key") or "").strip()
        if not 8 <= len(key) <= 128:
            raise ValidationError("Ugyldig fullføringsnøkkel.")
        self.backup_before_write()
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id,status,points FROM chore_completions WHERE idempotency_key=?", (key,)
            ).fetchone()
            if existing:
                return {**dict(existing), "duplicate": True}
            row = connection.execute(
                """SELECT k.id,k.assigned_to,k.lane,m.points,m.requires_approval,
                          m.repeat_mode,m.repeat_weekdays,m.repeat_target,f.name
                   FROM kanban_cards k JOIN family_chore_meta m ON m.card_id=k.id
                   JOIN family_members f ON f.id=? AND f.role='child'
                   WHERE k.id=? AND k.archived_at IS NULL AND m.visible_to_kids=1""",
                (member_id, chore_id),
            ).fetchone()
            if not row or row["assigned_to"].lower() != row["name"].lower():
                raise KeyError(chore_id)
            repeat_mode = row["repeat_mode"] or "once"
            if repeat_mode == "once" and row["lane"] not in {"todo", "inprogress"}:
                raise ValidationError("Gjøremålet er allerede ferdig.")
            today = dt.date.today()
            completed_at = iso_now()
            if repeat_mode == "weekly":
                repeat_weekdays = parse_weekdays(row["repeat_weekdays"])
                cycle = self._cycle_for_completion(
                    connection,
                    chore_id,
                    member_id,
                    repeat_mode,
                    repeat_weekdays,
                    int(row["repeat_target"] or len(repeat_weekdays)),
                    int(row["points"]),
                    today,
                )
                if cycle["status"] != "open":
                    raise ValidationError("Dette oppdraget venter allerede på godkjenning eller er ferdig for uken.")
                if connection.execute(
                    """SELECT 1 FROM chore_completions
                       WHERE card_id=? AND member_id=? AND cycle_id=? AND occurrence_date=?
                         AND status != 'rejected'""",
                    (chore_id, member_id, cycle["id"], today.isoformat()),
                ).fetchone():
                    raise ValidationError("Dette oppdraget er allerede registrert i dag.")
                completed_count = int(cycle["completed_count"]) + 1
                final = completed_count >= int(cycle["required_count"])
                status = "pending" if row["requires_approval"] else "awarded"
                awarded_points = int(row["points"])
                cursor = connection.execute(
                    """INSERT INTO chore_completions(
                           card_id,member_id,idempotency_key,status,points,completed_at,cycle_id,occurrence_date
                       ) VALUES(?,?,?,?,?,?,?,?)""",
                    (chore_id, member_id, key, status, awarded_points, completed_at, cycle["id"], today.isoformat()),
                )
                cycle_status = "pending" if final and row["requires_approval"] else ("awarded" if final else "open")
                connection.execute(
                    """UPDATE chore_cycles SET completed_count=?,status=?,decided_at=? WHERE id=?""",
                    (completed_count, cycle_status, completed_at if final and not row["requires_approval"] else None, cycle["id"]),
                )
                result = {
                    "id": cursor.lastrowid,
                    "status": status,
                    "points": awarded_points,
                    "duplicate": False,
                    "repeat_completed": completed_count,
                    "repeat_target": int(cycle["required_count"]),
                    "repeat_status": cycle_status,
                }
            else:
                status = "pending" if row["requires_approval"] else "awarded"
                cursor = connection.execute(
                    """INSERT INTO chore_completions(card_id,member_id,idempotency_key,status,points,completed_at)
                       VALUES(?,?,?,?,?,?)""",
                    (chore_id, member_id, key, status, row["points"], completed_at),
                )
                connection.execute(
                    "UPDATE kanban_cards SET lane='done',updated_at=datetime('now') WHERE id=?", (chore_id,)
                )
                result = {"id": cursor.lastrowid, "status": status, "points": row["points"], "duplicate": False}
        self.audit("chore.completed", {"card_id": chore_id, "member_id": member_id, "status": status})
        return result

    def decide_completion(self, completion_id: int, payload: dict[str, Any], parent_id: int) -> dict[str, Any]:
        decision = str(payload.get("decision", ""))
        if decision not in {"awarded", "rejected"}:
            raise ValidationError("Velg godkjenn eller avvis.")
        self.backup_before_write()
        with self.connect() as connection:
            current = connection.execute(
                "SELECT id,card_id,status,points,cycle_id FROM chore_completions WHERE id=?", (completion_id,)
            ).fetchone()
            if not current:
                raise KeyError(completion_id)
            if current["cycle_id"]:
                cycle = connection.execute(
                    """SELECT id,card_id,member_id,cycle_key,required_count,completed_count,status,points,created_at,decided_at
                       FROM chore_cycles WHERE id=?""", (current["cycle_id"],)
                ).fetchone()
                if not cycle or cycle["status"] not in {"open", "pending", "awarded"}:
                    raise ValidationError("Denne gjentakelsen er ikke klar for godkjenning.")
                now = iso_now()
                if current["status"] == "rejected":
                    return {**dict(current), "unchanged": True}
                if decision == "awarded":
                    if current["status"] == "awarded":
                        return {**dict(current), "unchanged": True}
                    connection.execute(
                        "UPDATE chore_completions SET status='awarded',approved_by=?,decided_at=? WHERE id=?",
                        (parent_id, now, completion_id),
                    )
                    pending_count = connection.execute(
                        "SELECT COUNT(*) FROM chore_completions WHERE cycle_id=? AND status='pending'",
                        (cycle["id"],),
                    ).fetchone()[0]
                    next_status = "awarded" if int(cycle["completed_count"]) >= int(cycle["required_count"]) and not pending_count else "open"
                    connection.execute(
                        "UPDATE chore_cycles SET status=?,decided_at=? WHERE id=?",
                        (next_status, now if next_status == "awarded" else None, cycle["id"]),
                    )
                else:
                    connection.execute(
                        "UPDATE chore_completions SET status='rejected',points=0,approved_by=?,decided_at=? WHERE id=?",
                        (parent_id, now, completion_id),
                    )
                    connection.execute(
                        "UPDATE chore_cycles SET status='open',completed_count=?,decided_at=NULL WHERE id=?",
                        (max(0, int(cycle["completed_count"]) - 1), cycle["id"]),
                    )
                result = dict(connection.execute(
                    "SELECT id,card_id,status,points,completed_at,decided_at FROM chore_completions WHERE id=?",
                    (completion_id,),
                ).fetchone())
                self.audit("completion.decided", {"id": completion_id, "status": decision, "parent_id": parent_id, "cycle_id": cycle["id"]})
                return result
            if current["status"] == "rejected" or (current["status"] == "awarded" and decision == "awarded"):
                return {**dict(current), "unchanged": True}
            connection.execute(
                """UPDATE chore_completions SET status=?,approved_by=?,decided_at=? WHERE id=?""",
                (decision, parent_id, iso_now(), completion_id),
            )
            if decision == "rejected":
                connection.execute(
                    "UPDATE kanban_cards SET lane='todo',updated_at=datetime('now') WHERE id=?", (current["card_id"],)
                )
            result = dict(connection.execute(
                "SELECT id,card_id,status,points,completed_at,decided_at FROM chore_completions WHERE id=?",
                (completion_id,),
            ).fetchone())
        self.audit("completion.decided", {"id": completion_id, "status": decision, "parent_id": parent_id})
        return result

    def set_reward(self, payload: dict[str, Any]) -> dict[str, Any]:
        member_id = self._integer(payload.get("member_id"), "Barn", 1, 1000000)
        title = str(payload.get("title") or "").strip()
        emoji = str(payload.get("emoji") or "🎯").strip()
        goal_type = str(payload.get("goal_type") or "points")
        unit = str(payload.get("unit_label") or ("kr" if goal_type == "currency" else "poeng")).strip()
        target = self._integer(payload.get("target_value"), "Mål", 1, 1000000)
        if not 1 <= len(title) <= 80 or goal_type not in {"points", "currency", "items"}:
            raise ValidationError("Ugyldig belønningsmål.")
        self.backup_before_write()
        created = iso_now()
        with self.connect() as connection:
            child = connection.execute("SELECT 1 FROM family_members WHERE id=? AND role='child'", (member_id,)).fetchone()
            if not child:
                raise ValidationError("Ukjent barn.")
            connection.execute("UPDATE reward_goals SET active=0 WHERE member_id=? AND active=1", (member_id,))
            cursor = connection.execute(
                """INSERT INTO reward_goals(member_id,title,emoji,goal_type,target_value,unit_label,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (member_id, title, emoji[:12], goal_type, target, unit[:20], created),
            )
            result = dict(connection.execute(
                """SELECT id,member_id,title,emoji,goal_type,target_value,unit_label,active,created_at,achieved_at
                   FROM reward_goals WHERE id=?""", (cursor.lastrowid,)
            ).fetchone())
        self.audit("reward.created", {"id": result["id"], "member_id": member_id, "target": target})
        return result

    def set_weekly_surprise(self, member_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        member_id = self._integer(member_id, "Barn", 1, 1000000)
        threshold = self._integer(payload.get("threshold_weeks"), "Uker", 1, 10000)
        title = str(payload.get("title") or "").strip()
        emoji = str(payload.get("emoji") or "🎁").strip()[:12]
        if not 1 <= len(title) <= 80:
            raise ValidationError("Overraskelsen må ha en tittel på 1–80 tegn.")
        self.backup_before_write()
        now = precise_iso_now()
        with self.connect() as connection:
            child = connection.execute("SELECT 1 FROM family_members WHERE id=? AND role='child'", (member_id,)).fetchone()
            if not child:
                raise ValidationError("Ukjent barn.")
            existing = connection.execute(
                "SELECT id FROM weekly_surprise_levels WHERE member_id=? AND threshold_weeks=?",
                (member_id, threshold),
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE weekly_surprise_levels SET title=?,emoji=?,active=1,updated_at=? WHERE id=?",
                    (title, emoji, now, existing[0]),
                )
                surprise_id = existing[0]
            else:
                cursor = connection.execute(
                    """INSERT INTO weekly_surprise_levels(member_id,threshold_weeks,title,emoji,created_at,updated_at)
                       VALUES(?,?,?,?,?,?)""",
                    (member_id, threshold, title, emoji, now, now),
                )
                surprise_id = cursor.lastrowid
            result = dict(connection.execute(
                "SELECT id,member_id,threshold_weeks,title,emoji,active FROM weekly_surprise_levels WHERE id=?",
                (surprise_id,),
            ).fetchone())
        self.audit("weekly_surprise.saved", {"id": result["id"], "member_id": member_id, "threshold": threshold})
        return result

    def delete_weekly_surprise(self, member_id: int, threshold: int) -> dict[str, Any]:
        member_id = self._integer(member_id, "Barn", 1, 1000000)
        threshold = self._integer(threshold, "Uker", 1, 10000)
        self.backup_before_write()
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE weekly_surprise_levels SET active=0,updated_at=? WHERE member_id=? AND threshold_weeks=?",
                (iso_now(), member_id, threshold),
            )
            if not cursor.rowcount:
                raise KeyError(threshold)
        self.audit("weekly_surprise.deleted", {"member_id": member_id, "threshold": threshold})
        return {"member_id": member_id, "threshold_weeks": threshold, "deleted": True}

    def reset_weekly_achievement(self, member_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        member_id = self._integer(member_id, "Barn", 1, 1000000)
        key = str(payload.get("idempotency_key") or "").strip()
        if not 8 <= len(key) <= 128:
            raise ValidationError("Ugyldig nullstillingsnøkkel.")
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT result_json FROM weekly_achievement_reset_operations WHERE idempotency_key=?",
                (key,),
            ).fetchone()
            if existing:
                return {**json.loads(existing[0]), "duplicate": True}
            child = connection.execute(
                "SELECT id FROM family_members WHERE id=? AND role='child'", (member_id,)
            ).fetchone()
            if not child:
                raise ValidationError("Ukjent barn.")
        self.backup_before_write()
        now = precise_iso_now()
        with self.connect() as connection:
            cycle = self._weekly_cycle(connection, member_id)
            snapshot = self.weekly_achievement_snapshot(connection, member_id, dt.date.today())
            requested_threshold = payload.get("threshold_weeks")
            selected = None
            if requested_threshold is not None:
                threshold = self._integer(requested_threshold, "Uker", 1, 10000)
                selected = connection.execute(
                    """SELECT threshold_weeks,title FROM weekly_surprise_levels
                       WHERE member_id=? AND threshold_weeks=? AND active=1""",
                    (member_id, threshold),
                ).fetchone()
                if not selected:
                    raise ValidationError("Denne overraskelsen finnes ikke.")
            elif snapshot["ready_surprises"]:
                ready = snapshot["ready_surprises"][-1]
                selected = {"threshold_weeks": ready["threshold_weeks"], "title": ready["title"]}
            connection.execute(
                "UPDATE weekly_achievement_cycles SET ended_at=? WHERE id=?",
                (now, cycle["id"]),
            )
            redemption_id = None
            if snapshot["full_tabs"] or selected:
                cursor = connection.execute(
                    """INSERT INTO weekly_achievement_redemptions(
                           member_id,cycle_id,full_weeks,threshold_weeks,title,created_at
                       ) VALUES(?,?,?,?,?,?)""",
                    (member_id, cycle["id"], snapshot["full_tabs"],
                     selected["threshold_weeks"] if selected else None,
                     selected["title"] if selected else "Manuell nullstilling", now),
                )
                redemption_id = cursor.lastrowid
            cursor = connection.execute(
                """INSERT INTO weekly_achievement_cycles(member_id,target_points,started_at)
                   VALUES(?,?,?)""",
                (member_id, cycle["target_points"], now),
            )
            result = {
                "member_id": member_id,
                "previous_full_tabs": snapshot["full_tabs"],
                # Compatibility alias for callers using the old field name.
                "previous_full_weeks": snapshot["full_tabs"],
                "claimed_surprise": dict(selected) if selected else None,
                "redemption_id": redemption_id,
                "new_cycle_id": cursor.lastrowid,
            }
            connection.execute(
                """INSERT INTO weekly_achievement_reset_operations(member_id,idempotency_key,result_json,created_at)
                   VALUES(?,?,?,?)""",
                (member_id, key, json.dumps(result, ensure_ascii=False), now),
            )
        self.audit("weekly_achievement.reset", {**result, "idempotency_key": key})
        return {**result, "duplicate": False}

    def reset_child(self, member_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        member_id = self._integer(member_id, "Barn", 1, 1000000)
        scope = str(payload.get("scope") or "both")
        if scope not in {"chores", "points", "both"}:
            raise ValidationError("Velg hva som skal nullstilles.")
        key = str(payload.get("idempotency_key") or "").strip()
        if not 8 <= len(key) <= 128:
            raise ValidationError("Ugyldig nullstillingsnøkkel.")
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT result_json FROM dashboard_reset_operations WHERE idempotency_key=?", (key,)
            ).fetchone()
            if existing:
                return {**json.loads(existing[0]), "duplicate": True}
            child = connection.execute(
                "SELECT id,name FROM family_members WHERE id=? AND role='child'", (member_id,)
            ).fetchone()
            if not child:
                raise ValidationError("Ukjent barn.")
        self.backup_before_write()
        now = iso_now()
        archived_chores = 0
        reset_points = False
        reset_achievement = False
        with self.connect() as connection:
            if scope in {"chores", "both"}:
                cursor = connection.execute(
                    """UPDATE kanban_cards SET archived_at=?,updated_at=?
                       WHERE archived_at IS NULL AND lower(assigned_to)=lower(?)
                         AND id IN (SELECT card_id FROM family_chore_meta WHERE visible_to_kids=1)""",
                    (now, now, child["name"]),
                )
                archived_chores = cursor.rowcount
                connection.execute(
                    """UPDATE family_chore_meta SET visible_to_kids=0,updated_at=?
                       WHERE visible_to_kids=1 AND card_id IN (
                           SELECT id FROM kanban_cards WHERE lower(assigned_to)=lower(?)
                       )""",
                    (now, child["name"]),
                )
                connection.execute(
                    """UPDATE chore_cycles SET status='reset',decided_at=?
                       WHERE member_id=? AND status IN ('open','pending')""",
                    (now, member_id),
                )
            if scope in {"points", "both"}:
                active_cycle = self._weekly_cycle(connection, member_id)
                connection.execute(
                    "UPDATE weekly_achievement_cycles SET ended_at=? WHERE id=? AND ended_at IS NULL",
                    (now, active_cycle["id"]),
                )
                connection.execute(
                    "INSERT INTO weekly_achievement_cycles(member_id,target_points,started_at) VALUES(?,?,?)",
                    (member_id, active_cycle["target_points"], precise_iso_now()),
                )
                reset_achievement = True
                goal = connection.execute(
                    """SELECT title,emoji,goal_type,target_value,unit_label
                       FROM reward_goals WHERE member_id=? AND active=1""",
                    (member_id,),
                ).fetchone()
                if goal:
                    connection.execute("UPDATE reward_goals SET active=0 WHERE member_id=? AND active=1", (member_id,))
                    goal_started = dt.datetime.now().astimezone().isoformat(timespec="microseconds")
                    connection.execute(
                        """INSERT INTO reward_goals(member_id,title,emoji,goal_type,target_value,unit_label,created_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        (member_id, goal["title"], goal["emoji"], goal["goal_type"], goal["target_value"], goal["unit_label"], goal_started),
                    )
                    reset_points = True
            result = {
                "member_id": member_id,
                "scope": scope,
                "archived_chores": archived_chores,
                "reset_points": reset_points,
                "reset_achievement": reset_achievement,
            }
            connection.execute(
                """INSERT INTO dashboard_reset_operations(member_id,scope,idempotency_key,result_json,created_at)
                   VALUES(?,?,?,?,?)""",
                (member_id, scope, key, json.dumps(result, ensure_ascii=False), now),
            )
        self.audit("child.reset", {**result, "idempotency_key": key})
        return {**result, "duplicate": False}


class FamilyApiHandler(BaseHTTPRequestHandler):
    server_version = "FamilyBotLocal/1.0"

    @property
    def app(self) -> "FamilyApiServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[familybot-api] {self.address_string()} {fmt % args}")

    def trusted_origin(self) -> bool:
        origin = self.headers.get("Origin")
        return trusted_portal_origin(origin, self.app.allowed_origins)

    def cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin and trusted_portal_origin(origin, self.app.allowed_origins):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def respond(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self.trusted_origin():
            self.respond(403, {"error": "Ukjent origin."})
            return
        self.send_response(204)
        self.cors()
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-FamilyBot-Local-Token, X-FamilyBot-Parent-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            try:
                with self.app.repository.connect() as connection:
                    connection.execute("SELECT 1").fetchone()
                self.respond(200, {"ok": True, "service": "familybot-dashboard-api", "at": iso_now()})
            except sqlite3.Error:
                self.respond(503, {"ok": False, "service": "familybot-dashboard-api"})
            return
        if not self.trusted_origin():
            self.respond(403, {"error": "Ukjent origin."})
            return
        if parsed.path == "/api/session":
            self.respond(200, {"token": self.app.session_token, "api": "familybot-local-v2"})
            return
        if not self.authorize_read():
            self.respond(403, {"error": "Lokal lesetilgang ble avvist."})
            return
        if parsed.path == "/api/dashboard":
            query = parse_qs(parsed.query)
            try:
                requested = dt.date.fromisoformat(query["date"][0]) if query.get("date") else None
                self.respond(200, self.app.repository.dashboard(requested))
            except ValueError:
                self.respond(400, {"error": "Ugyldig dato."})
            except sqlite3.Error as exc:
                self.log_error("dashboard database error: %s", type(exc).__name__)
                self.respond(503, {"error": "Familiedata er midlertidig utilgjengelig."})
            return
        week_plan = re.fullmatch(r"/api/children/(\d+)/week-plans/(\d+)", parsed.path)
        if week_plan:
            try:
                self.respond(200, {"week_plan": self.app.repository.week_plan_detail(int(week_plan.group(1)), int(week_plan.group(2)))})
            except KeyError:
                self.respond(404, {"error": "Ukeplanen ble ikke funnet."})
            except sqlite3.Error as exc:
                self.log_error("week plan database error: %s", type(exc).__name__)
                self.respond(503, {"error": "Ukeplanen er midlertidig utilgjengelig."})
            return
        self.respond(404, {"error": "Ikke funnet."})

    def read_payload(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValidationError("Ugyldig Content-Length.") from exc
        if not 0 <= length <= 16_384:
            raise ValidationError("Innholdet er for stort.")
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            raise ValidationError("Ugyldig JSON.") from exc
        if not isinstance(value, dict):
            raise ValidationError("Innholdet må være et objekt.")
        return value

    def authorize_mutation(self) -> bool:
        return self.trusted_origin() and secrets.compare_digest(
            self.headers.get("X-FamilyBot-Local-Token", ""), self.app.session_token
        )

    def authorize_read(self) -> bool:
        return self.authorize_mutation()

    def authorize_parent(self) -> bool:
        supplied = self.headers.get("X-FamilyBot-Parent-Token", "")
        return bool(supplied) and bool(self.app.parent_token) and self.authorize_mutation() and secrets.compare_digest(
            supplied, self.app.parent_token
        )

    def mutate(self, method: str) -> None:
        if not self.authorize_mutation():
            self.respond(403, {"error": "Lokal skrivetilgang ble avvist."})
            return
        path = urlparse(self.path).path
        try:
            if method == "POST" and path == "/api/parent/session":
                if not self.app.parent_login_allowed(self.client_address[0]):
                    self.respond(429, {"error": "For mange forsøk. Vent fem minutter."})
                    return
                if hmac.compare_digest(str(self.read_payload().get("pin") or ""), self.app.parent_pin):
                    self.app.record_parent_login(self.client_address[0], succeeded=True)
                    self.app.parent_token = secrets.token_urlsafe(32)
                    self.respond(200, {"parent_token": self.app.parent_token})
                else:
                    self.app.record_parent_login(self.client_address[0], succeeded=False)
                    self.respond(403, {"error": "Feil foreldrekode."})
                return
            complete = re.fullmatch(r"/api/chores/(\d+)/complete", path)
            if method == "POST" and complete:
                result = self.app.repository.complete_chore(int(complete.group(1)), self.read_payload())
                self.respond(201, {"completion": result})
                return
            if method == "POST" and path == "/api/chores":
                if not self.authorize_parent():
                    self.respond(403, {"error": "Foreldremodus kreves."})
                    return
                self.respond(201, {"chore": self.app.repository.create_child_chore(self.read_payload())})
                return
            completion = re.fullmatch(r"/api/completions/(\d+)", path)
            if method == "PATCH" and completion:
                if not self.authorize_parent():
                    self.respond(403, {"error": "Foreldremodus kreves."})
                    return
                result = self.app.repository.decide_completion(
                    int(completion.group(1)), self.read_payload(), self.app.parent_member_id
                )
                self.respond(200, {"completion": result})
                return
            if method == "POST" and path == "/api/rewards":
                if not self.authorize_parent():
                    self.respond(403, {"error": "Foreldremodus kreves."})
                    return
                self.respond(201, {"reward": self.app.repository.set_reward(self.read_payload())})
                return
            if method == "POST" and path == "/api/kanban":
                if not self.authorize_parent():
                    self.respond(403, {"error": "Foreldremodus kreves."})
                    return
                self.respond(201, {"card": self.app.repository.create_chore(self.read_payload())})
                return
            kanban = re.fullmatch(r"/api/kanban/(\d+)", path)
            if kanban and method in {"PATCH", "DELETE"}:
                if not self.authorize_parent():
                    self.respond(403, {"error": "Foreldremodus kreves."})
                    return
                card_id = int(kanban.group(1))
                if method == "PATCH":
                    self.respond(200, {"card": self.app.repository.update_chore(card_id, self.read_payload())})
                else:
                    self.respond(200, {"card": self.app.repository.archive_chore(card_id)})
                return
            weekly_surprise = re.fullmatch(r"/api/children/(\d+)/weekly-achievement/surprises", path)
            if method == "POST" and weekly_surprise:
                if not self.authorize_parent():
                    self.respond(403, {"error": "Foreldremodus kreves."})
                    return
                self.respond(201, {"surprise": self.app.repository.set_weekly_surprise(int(weekly_surprise.group(1)), self.read_payload())})
                return
            weekly_surprise_delete = re.fullmatch(r"/api/children/(\d+)/weekly-achievement/surprises/(\d+)", path)
            if method == "DELETE" and weekly_surprise_delete:
                if not self.authorize_parent():
                    self.respond(403, {"error": "Foreldremodus kreves."})
                    return
                self.respond(200, {"surprise": self.app.repository.delete_weekly_surprise(int(weekly_surprise_delete.group(1)), int(weekly_surprise_delete.group(2)))})
                return
            weekly_reset = re.fullmatch(r"/api/children/(\d+)/weekly-achievement/reset", path)
            if method == "POST" and weekly_reset:
                if not self.authorize_parent():
                    self.respond(403, {"error": "Foreldremodus kreves."})
                    return
                self.respond(200, {"reset": self.app.repository.reset_weekly_achievement(int(weekly_reset.group(1)), self.read_payload())})
                return
            reset = re.fullmatch(r"/api/children/(\d+)/reset", path)
            if method == "POST" and reset:
                if not self.authorize_parent():
                    self.respond(403, {"error": "Foreldremodus kreves."})
                    return
                self.respond(200, {"reset": self.app.repository.reset_child(int(reset.group(1)), self.read_payload())})
                return
            match = re.fullmatch(r"/api/chores/(\d+)(/restore)?", path)
            if not match:
                self.respond(404, {"error": "Ikke funnet."})
                return
            chore_id = int(match.group(1))
            if not self.authorize_parent():
                self.respond(403, {"error": "Foreldremodus kreves."})
                return
            if method == "PATCH" and not match.group(2):
                self.respond(200, {"chore": self.app.repository.update_chore(chore_id, self.read_payload())})
            elif method == "DELETE" and not match.group(2):
                self.respond(200, {"chore": self.app.repository.archive_chore(chore_id), "undo": True})
            elif method == "POST" and match.group(2):
                self.respond(200, {"chore": self.app.repository.restore_chore(chore_id)})
            else:
                self.respond(405, {"error": "Metoden støttes ikke."})
        except ValidationError as exc:
            self.respond(400, {"error": str(exc)})
        except KeyError:
            self.respond(404, {"error": "Gjøremålet finnes ikke eller har allerede denne statusen."})
        except sqlite3.Error as exc:
            self.log_error("mutation database error: %s", type(exc).__name__)
            self.respond(503, {"error": "Endringen kunne ikke lagres akkurat nå."})

    def do_POST(self) -> None:  # noqa: N802
        self.mutate("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self.mutate("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self.mutate("DELETE")


class FamilyApiServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], repository: FamilyRepository, parent_pin: str,
                 allowed_origins: set[str] | None = None):
        super().__init__(address, FamilyApiHandler)
        self.repository = repository
        self.session_token = secrets.token_urlsafe(32)
        self.parent_pin = parent_pin
        self.parent_token = ""
        self.allowed_origins = allowed_origins or configured_origins(repository.workspace)
        self._parent_failures: dict[str, list[float]] = {}
        self._parent_failure_lock = threading.Lock()
        with repository.connect() as connection:
            parent = connection.execute("SELECT id FROM family_members WHERE role='parent' ORDER BY id LIMIT 1").fetchone()
        self.parent_member_id = int(parent[0]) if parent else 1

    def parent_login_allowed(self, client: str) -> bool:
        cutoff = time.monotonic() - 300
        with self._parent_failure_lock:
            recent = [value for value in self._parent_failures.get(client, []) if value >= cutoff]
            self._parent_failures[client] = recent
            return len(recent) < 5

    def record_parent_login(self, client: str, *, succeeded: bool) -> None:
        with self._parent_failure_lock:
            if succeeded:
                self._parent_failures.pop(client, None)
            else:
                self._parent_failures.setdefault(client, []).append(time.monotonic())


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local FamilyBot console API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("FAMILYBOT_DB_PATH", DEFAULT_DB)))
    parser.add_argument("--workspace", type=Path, default=Path(os.environ.get("FAMILYBOT_WORKSPACE", DEFAULT_WORKSPACE)))
    parser.add_argument("--lan", action="store_true")
    parser.add_argument("--parent-pin-file", type=Path, default=Path(__file__).resolve().parent.parent / "runtime/parent-pin.txt")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"} and not (args.lan and args.host == "0.0.0.0"):
        raise SystemExit("LAN bind requires --lan and --host 0.0.0.0.")
    if not args.db.is_file():
        raise SystemExit(f"FamilyBot database not found: {args.db}")
    try:
        parent_pin = args.parent_pin_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SystemExit(f"Parent PIN file unavailable: {args.parent_pin_file}") from exc
    if not re.fullmatch(r"\d{4,8}", parent_pin):
        raise SystemExit("Parent PIN must contain 4-8 digits.")
    server = FamilyApiServer((args.host, args.port), FamilyRepository(args.db, args.workspace), parent_pin)
    print(f"FamilyBot local API: http://{args.host}:{args.port}")
    print(f"Database: {args.db}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
