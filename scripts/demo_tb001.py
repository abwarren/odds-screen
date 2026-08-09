"""TB-001 demo: one live game through the ingest path, end-to-end.

Walks the full lifecycle against the REAL stack:
  tick 1: fresh event, 5 markets, 10 selections
  tick 2: ft over odds change 1.85 -> 1.75
  tick 3: ft line move 222.5 -> 223.5 (both sides)
  tick 4: exact duplicate (dedupe -> zero appends)

Run:  .venv/bin/python scripts/demo_tb001.py > docs/tracer_bullets/TB-001/evidence/demo.log
Requires: compose stack up, DB truncated for a clean run.
"""
import asyncio
import json

import asyncpg
import httpx

API = "http://localhost:8002"
DB_URL = "postgresql://postgres:postgres@localhost:5434/odds"
PERIODS = ["q1", "q2", "q3", "q4", "ft"]
REF = "nba-2026-08-09-lakers-celtics"


def payload(over=1.85, under=1.90, line=222.5, period_odds=None, period_lines=None):
    markets = []
    for p in PERIODS:
        o, u = over, under
        if period_odds and p in period_odds:
            o = period_odds[p].get("over", over)
            u = period_odds[p].get("under", under)
        ln = line
        if period_lines and p in period_lines:
            ln = period_lines[p]
        markets.append({
            "period": p, "market_type": "total_points", "status": "open",
            "selections": [
                {"side": "over", "line_value": ln, "odds": o},
                {"side": "under", "line_value": ln, "odds": u},
            ],
        })
    return {
        "bookmaker": "pokerbet",
        "event": {
            "external_ref": REF,
            "competition": "NBA", "sport": "basketball",
            "home_team": "Lakers", "away_team": "Celtics",
            "status": "live", "period_code": "q3",
            "clock_seconds": 420, "home_score": 72, "away_score": 68,
        },
        "markets": markets,
    }


def board_rows(client):
    return client.get(f"{API}/board").json()["events"]


def print_board(client, label):
    print(f"\n=== /board — {label} ===")
    rows = board_rows(client)
    by_period = {}
    for r in rows:
        by_period.setdefault(r["period"], []).append(
            f"{r['side']} {r['line_value']} @ {r['odds']}"
        )
    if not by_period:
        print("  (empty)")
        return
    ev = rows[0]
    print(f"  {ev['home_team']} {ev['home_score']} - {ev['away_score']} {ev['away_team']}"
          f"  | {ev['period_code']} {ev['clock_seconds']}s")
    for p in PERIODS:
        print(f"  {p:>3}: " + "  ".join(by_period.get(p, [])))


async def main():
    client = httpx.Client(timeout=10)
    conn = await asyncpg.connect(DB_URL)

    print("=" * 64)
    print("TB-001 DEMO — live basketball totals ingest path")
    print("=" * 64)

    # tick 1
    r = client.post(f"{API}/ingest", json=payload())
    print(f"\nTICK 1 — fresh event, 5 markets, 10 selections")
    print(f"  POST /ingest -> {r.status_code} {json.dumps(r.json())}")
    print_board(client, "after tick 1")

    # tick 2
    r = client.post(f"{API}/ingest", json=payload(
        period_odds={"ft": {"over": 1.75}}))
    print(f"\nTICK 2 — ft OVER odds 1.85 -> 1.75")
    print(f"  POST /ingest -> {r.status_code} {json.dumps(r.json())}")
    print_board(client, "after tick 2")

    # tick 3
    r = client.post(f"{API}/ingest", json=payload(
        period_odds={"ft": {"over": 1.80, "under": 1.85}},
        period_lines={"ft": 223.5}))
    print(f"\nTICK 3 — ft LINE MOVE 222.5 -> 223.5 (both sides)")
    print(f"  POST /ingest -> {r.status_code} {json.dumps(r.json())}")
    print_board(client, "after tick 3")

    # tick 4
    r = client.post(f"{API}/ingest", json=payload(
        period_odds={"ft": {"over": 1.80, "under": 1.85}},
        period_lines={"ft": 223.5}))
    print(f"\nTICK 4 — exact duplicate of tick 3 (dedupe check)")
    print(f"  POST /ingest -> {r.status_code} {json.dumps(r.json())}")

    # DB state
    print("\n=== Postgres state ===")
    for label, sql in [
        ("events", "SELECT id, home_team, away_team, status, period_code, "
                   "home_score, away_score, last_seen_at FROM events"),
        ("markets", "SELECT id, event_id, period_id, market_type_id, status FROM markets"),
        ("selections", "SELECT id, market_id, side, line_value, is_open FROM selections ORDER BY id"),
        ("odds_history", "SELECT id, selection_id, odds, implied_prob, source "
                         "FROM odds_history ORDER BY id"),
        ("v_current_odds", "SELECT selection_id, side, line_value, odds, captured_at "
                           "FROM v_current_odds ORDER BY selection_id"),
    ]:
        rows = await conn.fetch(sql)
        print(f"\n  {label} ({len(rows)} rows)")
        for row in rows:
            print("   ", dict(row))

    await conn.close()
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
