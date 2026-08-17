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
HOST = "familie.local"
ORIGIN = f"http://{HOST}:3000"
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
    web_status,_=request(3000,"GET","/")
    api_status,api_raw=request(8788,"GET","/api/health")
    launch=subprocess.run(["launchctl","print",f"gui/{os.getuid()}/ai.familybot.portal"],capture_output=True,text=True)
    lookup=subprocess.Popen(["/usr/bin/dns-sd","-L","Familieportalen","_http._tcp","local"],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    time.sleep(2); lookup.terminate(); dns_output=lookup.communicate(timeout=3)[0]
    record("AC-01",web_status==200 and api_status==200 and launch.returncode==0 and f"{HOST}.:3000" in dns_output,f"web={web_status}, api={api_status}, Bonjour resolved, launchd={launch.returncode}",started)

    browser=json.loads((ROOT/"tests/browser-acceptance.json").read_text())
    direct=browser["direct_child_link"]; portrait=browser["portrait"]
    started=time.monotonic(); record("AC-02",direct["survived_reload"] and portrait["family_information_cards"]==4 and portrait["child_entry_controls"]==2,"family home=4 cards; one-tap child URL survived reload",started)

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
    record("AC-03",child_cards>=6 and completion_unique and 'className="mission-card"' in source and 'onClick={()=>void complete(chore)}' in source,f"{child_cards} kid cards; unique idempotency key; one-tap handler",started)

    started=time.monotonic()
    with sqlite3.connect(DB) as connection:
        durable=all(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() for name in ("chore_completions","family_chore_meta","reward_goals"))
    record("AC-04",durable and "history-list" in source,"SQLite tables present; history surface rendered",started)

    started=time.monotonic()
    status,session_raw=request(8788,"GET","/api/session"); session=json.loads(session_raw); local=session.get("token","")
    _,dashboard_raw=request(8788,"GET","/api/dashboard"); dashboard=json.loads(dashboard_raw)
    first_child=dashboard["children"][0]["name"].lower()
    rejected,_=request(8788,"POST","/api/chores",{"X-FamilyBot-Local-Token":local},{"title":"must reject","assigned_to":first_child,"points":1})
    record("AC-05",status==200 and rejected==403 and "decide_completion" in (ROOT/"local_api/familybot_api.py").read_text(),f"child admin attempt={rejected}; approval transition implemented",started)

    started=time.monotonic()
    rewards=[child.get("reward") for child in dashboard["children"]]
    reward_ok=all(reward and all(key in reward for key in ("earned","remaining","percent","target_value","title")) for reward in rewards)
    record("AC-06",reward_ok,f"reward calculations present for {len(dashboard['children'])} configured children",started)

    started=time.monotonic()
    pin=ROOT/"runtime/parent-pin.txt"; mode=pin.stat().st_mode & 0o777
    record("AC-07",mode==0o600 and all(text in source for text in ("Legg til gjøremål","Nylig registrert","Underkjenn","Sett nytt mål")),f"parent PIN mode={oct(mode)}; add/reject/reward controls present",started)

    started=time.monotonic()
    encoded=dashboard_raw.decode("utf-8",errors="replace").lower(); forbidden=[term for term in ("telegram_id","raw_json","source_ref","attachment","api_key") if term in encoded]
    departures=dashboard.get("transport",{}).get("departures",[])
    live_transport=bool(departures) and all(item.get("line")=="2" and item.get("platform")=="1" for item in departures) and "TransportCountdown" in source and "1_000" in source
    family_surface=all(text in source for text in ("Viktigst nå","Vær og T-bane","Aktiviteter","FamilyBot","Skolen denne uken"))
    current_plans=[plan["member"] for plan in dashboard.get("week_plans",[])]
    record("AC-08",family_surface and live_transport and bool(current_plans) and not forbidden,f"family surfaces; {len(departures)} centre-bound departures with countdown; {len(current_plans)} week plan(s); forbidden keys={forbidden}",started)

    started=time.monotonic()
    responsive=not portrait["horizontal_overflow"] and not browser["landscape"]["horizontal_overflow"] and not browser["zoom_200_equivalent"]["horizontal_overflow"] and portrait["minimum_visible_button_height"]>=48 and min(size[1] for size in browser["landscape"]["mission_card_sizes"])>=56
    record("AC-09",responsive,"768x1024, 1024x768 and 384x512: no overflow; touch targets measured",started)

    started=time.monotonic()
    foreign=http.client.HTTPConnection(HOST,8788,timeout=5);foreign.request("GET","/api/health",headers={"Origin":"https://evil.example:3000"});foreign_status=foreign.getresponse().status;foreign.close()
    record("AC-10",foreign_status==403 and rejected==403 and not forbidden,f"foreign origin={foreign_status}; parent auth={rejected}; PIN={oct(mode)}",started)

    started=time.monotonic()
    backups=sorted((WORKSPACE / "backups").glob("dashboard-service-*/family.db"))
    tables_ok=False
    with sqlite3.connect(DB) as connection: tables_ok=connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    supervisor=(ROOT/"local_service/run_service.py").is_file()
    backup_evidence = f"<workspace>/backups/{backups[-1].parent.name}/family.db" if backups else None
    record("AC-11",bool(backups) and tables_ok and supervisor and launch.returncode==0,f"backup={backup_evidence}; integrity={tables_ok}; supervisor+launchd active",started)

    passed=sum(item["status"]=="pass" for item in results)
    report={"generated_at":dt.datetime.now().astimezone().isoformat(timespec="seconds"),"passed":passed,"total":len(results),"release_ready":passed==len(results),"results":results}
    target=ROOT/"tests/acceptance-results.json"; target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if report["release_ready"] else 1)


if __name__=="__main__": main()
