"""TB-003 demo: remote bet placement lifecycle, end-to-end against the live stack.

  seed event via /ingest -> POST /bets (manual) -> /bridge/commands shows it
  -> /bridge/report delivered -> /bridge/report confirmed -> GET /bets

Run:  .venv/bin/python scripts/demo_tb003.py > docs/tracer_bullets/TB-003/evidence/demo.log
Requires: compose stack up, bets table clean.
"""
import asyncio
import json
import uuid

import asyncpg
import httpx

API = "http://localhost:8002"
DB_URL = "postgresql://postgres:postgres@localhost:5434/odds"
TOKEN = "dev-token-change-me"
HDRS = {"X-Bet-Token": TOKEN, "Content-Type": "application/json"}

PERIODS = ["q1", "q2", "q3", "q4", "ft"]
REF = f"nba-{uuid.uuid4().hex[:8]}"


def seed_payload():
    return {
        "bookmaker": "pokerbet",
        "event": {"external_ref": REF, "competition": "NBA", "sport": "basketball",
                  "home_team": "Lakers", "away_team": "Celtics",
                  "status": "live", "period_code": "q3", "clock_seconds": 420,
                  "home_score": 72, "away_score": 68},
        "markets": [
            {"period": p, "market_type": "total_points", "status": "open",
             "selections": [
                 {"side": "over", "line_value": 222.5, "odds": 1.85},
                 {"side": "under", "line_value": 222.5, "odds": 1.90},
             ]}
            for p in PERIODS
        ],
    }


async def main():
    client = httpx.Client(timeout=10)
    conn = await asyncpg.connect(DB_URL)

    print("=" * 64)
    print("TB-003 DEMO — remote bet placement from the odds screen")
    print("=" * 64)

    r = client.post(f"{API}/ingest", json=seed_payload())
    print(f"\nseed event via /ingest -> {r.status_code}")

    rows = client.get(f"{API}/board").json()["events"]
    ft_over = next(x for x in rows if x["period"] == "ft" and x["side"] == "over")
    print(f"board ft over: selection_id={ft_over['selection_id']} "
          f"line={ft_over['line_value']} odds={ft_over['odds']}")

    body = {"selection_id": ft_over["selection_id"], "stake": 50, "mode": "manual",
            "idempotency_key": f"demo-{uuid.uuid4().hex[:12]}"}
    r = client.post(f"{API}/bets", json=body, headers=HDRS)
    bet = r.json()
    print(f"\nPOST /bets -> {r.status_code} {json.dumps(bet)}")

    cmds = client.get(f"{API}/bridge/commands?bookmaker=pokerbet", headers=HDRS).json()["commands"]
    cmd = next(c for c in cmds if c["bet_id"] == bet["id"])
    print(f"\nbridge command -> {json.dumps(cmd)}")
    print("(the Tampermonkey overlay on pokerbet.co.za pulls this, navigates to the")
    print(" game, fills the slip with Over 222.5 @ 1.85, sets stake R50, then:")
    print(" - manual mode: user clicks Place Bet on PokerBet")
    print(" - auto mode:   overlay verifies slip odds then clicks Place Bet itself")

    r = client.post(f"{API}/bridge/report",
                    json={"bet_id": bet["id"], "status": "delivered"}, headers=HDRS)
    print(f"\noverlay reports delivered -> {r.status_code} {r.json()}")

    pending = client.get(f"{API}/bridge/commands?bookmaker=pokerbet", headers=HDRS).json()["commands"]
    print(f"pending commands now: {len(pending)} (bet no longer queued)")

    r = client.post(f"{API}/bridge/report",
                    json={"bet_id": bet["id"], "status": "confirmed"}, headers=HDRS)
    print(f"overlay reports confirmed -> {r.status_code} {r.json()}")

    bets = client.get(f"{API}/bets", headers=HDRS).json()["bets"]
    mine = next(b for b in bets if b["id"] == bet["id"])
    print(f"\nGET /bets -> #{mine['id']} {mine['side']} {mine['line_value']} "
          f"@ {mine['odds_at_request']} stake R{mine['stake']} status={mine['status']}")

    n = await conn.fetchval("SELECT count(*) FROM bets WHERE idempotency_key LIKE 'demo-%'")
    print(f"\nbets table rows from this demo: {n}")
    await conn.close()
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
