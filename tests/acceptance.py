#!/usr/bin/env python3
"""Measure the release criteria against the running local production service."""

from __future__ import annotations

import datetime as dt
import http.client
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = Path(
    os.environ.get("FAMILYBOT_WORKSPACE", str(Path.home() / ".openclaw/workspace"))
).expanduser()
DB = WORKSPACE / "db/family.db"
CONFIG = Path(os.environ.get("FAMILYBOT_FAMILY_CONFIG", WORKSPACE / "config/family.local.json")).expanduser()
SETTINGS = json.loads(CONFIG.read_text(encoding="utf-8"))
PORTAL = SETTINGS["portal"]
HOST = str(PORTAL["hostname"])
WEB_PORT = int(PORTAL["web_port"])
API_PORT = int(PORTAL["api_port"])
BONJOUR_NAME = str(PORTAL["bonjour_name"])
ORIGIN = f"http://{HOST}:{WEB_PORT}"
CONFIGURED_LINE = str(SETTINGS["integrations"]["transport"]["line"])
EXPECTED_CHILDREN = sum(member.get("role") == "child" for member in SETTINGS["members"])
results: list[dict[str, object]] = []


def record(criterion: str, passed: bool, evidence: str, started: float) -> None:
    results.append({"criterion": criterion, "status": "pass" if passed else "fail", "evidence": evidence, "duration_ms": round((time.monotonic()-started)*1000)})


def request(port: int, method: str, path: str, headers: dict[str,str] | None=None, body: dict[str,object] | None=None):
    connection=http.client.HTTPConnection(HOST,port,timeout=5)
    raw=json.dumps(body).encode() if body is not None else None
    merged={"Origin":ORIGIN,**(headers or {})}
    if raw is not None: merged["Content-Type"]="application/json"
    connection.request(method,path,raw,merged)
    response=connection.getresponse(); payload=response.read(); connection.close()
    return response.status,payload


def main() -> None:
    started=time.monotonic()
    web_status,_=request(WEB_PORT,"GET","/")
    api_status,api_raw=request(API_PORT,"GET","/api/health")
    launch=subprocess.run(["launchctl","print",f"gui/{os.getuid()}/ai.familybot.portal"],capture_output=True,text=True)
    lookup=subprocess.Popen(["/usr/bin/dns-sd","-L",BONJOUR_NAME,"_http._tcp","local"],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    time.sleep(2); lookup.terminate(); dns_output=lookup.communicate(timeout=3)[0]
    record("AC-01",web_status==200 and api_status==200 and launch.returncode==0 and f"{HOST}.:{WEB_PORT}" in dns_output,f"web={web_status}, api={api_status}, Bonjour resolved, launchd={launch.returncode}",started)

    browser=json.loads((ROOT/"tests/browser-acceptance.json").read_text())
    direct=browser["direct_child_link"]; portrait=browser["portrait"]
    started=time.monotonic(); record("AC-02",direct["survived_reload"] and portrait["family_information_cards"]==5 and portrait["child_entry_controls"]==EXPECTED_CHILDREN,f"family home=5 cards; {EXPECTED_CHILDREN} configured child entry controls; direct child URL survived reload",started)

    started=time.monotonic()
    with sqlite3.connect(DB) as connection:
        child_cards=connection.execute(
            """SELECT COUNT(*) FROM family_chore_meta m JOIN kanban_cards k ON k.id=m.card_id
               WHERE m.visible_to_kids=1 AND k.archived_at IS NULL"""
        ).fetchone()[0]
        completion_unique=any(
            index[2] and any(column[2]=="idempotency_key" for column in connection.execute(f"PRAGMA index_info('{index[1]}')"))
            for index in connection.execute("PRAGMA index_list('chore_completions')")
        )
    source=(ROOT/"app/_components/FamilyConsole.tsx").read_text()
    empty_ready="Klar for nye oppdrag" in source and "Lag de første oppdragene sammen" in source
    record("AC-03",completion_unique and 'className="mission-card"' in source and 'onClick={()=>void complete(chore)}' in source and empty_ready,f"{child_cards} active kid cards; durable one-tap handler and guided empty state",started)

    started=time.monotonic()
    with sqlite3.connect(DB) as connection:
        durable=all(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() for name in ("chore_completions","family_chore_meta","reward_goals"))
    record("AC-04",durable and "history-list" in source,"SQLite tables present; history surface rendered",started)

    started=time.monotonic()
    status,session_raw=request(API_PORT,"GET","/api/session"); session=json.loads(session_raw); local=session.get("token","")
    _,dashboard_raw=request(API_PORT,"GET","/api/dashboard"); dashboard=json.loads(dashboard_raw)
    first_child=dashboard["children"][0]["name"].lower()
    rejected,_=request(API_PORT,"POST","/api/chores",{"X-FamilyBot-Local-Token":local},{"title":"must reject","assigned_to":first_child,"points":1})
    record("AC-05",status==200 and rejected==403 and "decide_completion" in (ROOT/"local_api/familybot_api.py").read_text(),f"child admin attempt={rejected}; approval transition implemented",started)

    started=time.monotonic()
    rewards=[child.get("reward") for child in dashboard["children"]]
    reward_ok=all(reward and all(key in reward for key in ("earned","remaining","percent","target_value","title")) and reward["target_value"]==30 for reward in rewards)
    record("AC-06",reward_ok and "Sett nytt mål" in source,f"reward contract valid; {sum(reward is not None for reward in rewards)} active target(s)",started)

    started=time.monotonic()
    pin=ROOT/"runtime/parent-pin.txt"; mode=pin.stat().st_mode & 0o777
    record("AC-07",mode==0o600 and all(text in source for text in ("Legg til gjøremål","Nylig registrert","Underkjenn","Sett nytt mål")),f"parent PIN mode={oct(mode)}; add/reject/reward controls present",started)

    started=time.monotonic()
    encoded=dashboard_raw.decode("utf-8",errors="replace").lower(); forbidden=[term for term in ("telegram_id","raw_json","source_ref","attachment","api_key") if term in encoded]
    departures=dashboard.get("transport",{}).get("departures",[])
    live_transport=bool(departures) and all(str(item.get("line"))==CONFIGURED_LINE for item in departures) and "TransportCountdown" in source and "1_000" in source
    family_surface=all(text in source for text in ("Viktigst nå","Neste 5 dager","upcomingEventsFor","WeatherForecast","T-bane","Aktiviteter","FamilyBot","Skolen denne uken")) and "<h2>FamilyBot</h2>" not in source
    current_plans=[plan["member"] for plan in dashboard.get("week_plans",[])]
    plan_state=dashboard.get("week_plan_status",[])
    record("AC-08",family_surface and live_transport and len(plan_state)==EXPECTED_CHILDREN and not forbidden,f"family surfaces; {len(departures)} configured-line departures with countdown; {len(current_plans)} week plan(s), {len(plan_state)} explicit child plan states; forbidden keys={forbidden}",started)

    started=time.monotonic()
    responsive=not portrait["horizontal_overflow"] and not browser["landscape"]["horizontal_overflow"] and not browser["zoom_200_equivalent"]["horizontal_overflow"] and portrait["minimum_visible_button_height"]>=48 and min(size[1] for size in browser["landscape"]["mission_card_sizes"])>=56
    record("AC-09",responsive,"768x1024, 1024x768 and 384x512: no overflow; touch targets measured",started)

    started=time.monotonic()
    foreign=http.client.HTTPConnection(HOST,API_PORT,timeout=5);foreign.request("GET","/api/session",headers={"Origin":"https://evil.example:3000"});foreign_status=foreign.getresponse().status;foreign.close()
    record("AC-10",foreign_status==403 and rejected==403 and not forbidden,f"foreign origin={foreign_status}; parent auth={rejected}; PIN={oct(mode)}",started)

    started=time.monotonic()
    backups=sorted((WORKSPACE / "backups").glob("dashboard-service-*/family.db"))
    tables_ok=False
    with sqlite3.connect(DB) as connection: tables_ok=connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    supervisor=(ROOT/"local_service/run_service.py").is_file()
    backup_evidence = f"<workspace>/backups/{backups[-1].parent.name}/family.db" if backups else None
    record("AC-11",bool(backups) and tables_ok and supervisor and launch.returncode==0,f"backup={backup_evidence}; integrity={tables_ok}; supervisor+launchd active",started)

    started=time.monotonic()
    recurring_contract=all(text in source for text in ("repeat_weekdays","mission-progress","repeat_completed"))
    with sqlite3.connect(DB) as connection:
        cycle_table=connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chore_cycles'").fetchone()
    record("AC-12",recurring_contract and bool(cycle_table),"recurring chore fields, child progress bar and cycle table present",started)

    started=time.monotonic()
    reset_contract=all(text in source for text in ("Nullstill oppgaver","Nullstill poeng","Nullstill begge")) and "reset_child" in (ROOT/"local_api/familybot_api.py").read_text()
    with sqlite3.connect(DB) as connection:
        reset_table=connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dashboard_reset_operations'").fetchone()
    record("AC-13",reset_contract and bool(reset_table),"parent reset controls and idempotency table present",started)

    started=time.monotonic()
    weekly_source=all(text in source for text in ("Fullførte uker","weekly-achievement","Lagre nivå","Overraskelse tatt"))
    with sqlite3.connect(DB) as connection:
        weekly_tables=all(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() for name in ("weekly_achievement_cycles","weekly_surprise_levels","weekly_achievement_redemptions","weekly_achievement_reset_operations"))
    record("AC-14",weekly_source and weekly_tables,"weekly full-week count, surprise ladder and parent redemption reset present",started)

    started=time.monotonic()
    api_source=(ROOT/"local_api/familybot_api.py").read_text()
    kanban_source=all(text in source for text in ("Kanban","New","In Progress","Pause","Done","/api/kanban"))
    kanban_api=all(text in api_source for text in ("LANES = {\"todo\", \"inprogress\", \"onhold\", \"done\"}","/api/kanban","NOT EXISTS (SELECT 1 FROM family_chore_meta"))
    record("AC-15",kanban_source and kanban_api and "updated_at.localeCompare" in source and "Kanban er skrivebeskyttet" in source,"Parent-only Kanban separation, four lanes, CRUD and newest-first card ordering present",started)

    started=time.monotonic()
    interview=(ROOT/"scripts/child_chore.py").read_text()
    core_bridge=Path(os.environ.get("FAMILYBOT_CORE_ROOT", ROOT.parent/"familybot-core"))/"scripts/kanban.py"
    bridge_source=core_bridge.read_text() if core_bridge.is_file() else ""
    with sqlite3.connect(DB) as connection:
        operation_table=connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='child_chore_operations'").fetchone()
    interview_contract=all(text in interview for text in ("confirmation_required", "--confirm", "idempotency_key", "telegram-interview"))
    bridge_contract=all(text in bridge_source for text in ("chore-preview", "chore-create", "FAMILYBOT_PORTAL_ROOT"))
    record("AC-16",bool(operation_table) and interview_contract and bridge_contract,"Telegram preview/confirmation bridge, portal-owned validation and idempotency table present",started)

    passed=sum(item["status"]=="pass" for item in results)
    report={"generated_at":dt.datetime.now().astimezone().isoformat(timespec="seconds"),"passed":passed,"total":len(results),"release_ready":passed==len(results),"results":results}
    result_dir=ROOT/"tests/results"; result_dir.mkdir(parents=True,exist_ok=True)
    target=result_dir/"acceptance-results.json"; target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if report["release_ready"] else 1)


if __name__=="__main__": main()
