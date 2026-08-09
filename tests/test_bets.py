"""Live loopback tests for remote bet placement (TB-003).

Hits the REAL stack (api:8002, db:5434). Requires the compose stack up with
BET_TOKEN set (dev token from docker-compose.yml).
"""
import uuid

import asyncpg
import httpx
import pytest

API = "http://localhost:8002"
DB_URL = "postgresql://postgres:postgres@localhost:5434/odds"
TOKEN = "dev-token-change-me"

PERIODS = ["q1", "q2", "q3", "q4", "ft"]
LIVE_EVENT = {
    "status": "live", "period_code": "q3", "clock_seconds": 420,
    "home_score": 72, "away_score": 68,
}


@pytest.fixture(scope="module", autouse=True)
async def clean_bets():
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute("TRUNCATE bets RESTART IDENTITY")
    finally:
        await conn.close()


def make_payload(ref):
    return {
        "bookmaker": "pokerbet",
        "event": {"external_ref": ref, "competition": "NBA", "sport": "basketball",
                  "home_team": "Lakers", "away_team": "Celtics", **LIVE_EVENT},
        "markets": [
            {"period": p, "market_type": "total_points", "status": "open",
             "selections": [
                 {"side": "over", "line_value": 222.5, "odds": 1.85},
                 {"side": "under", "line_value": 222.5, "odds": 1.90},
             ]}
            for p in PERIODS
        ],
    }


def seed_event(client, ref=None):
    ref = ref or f"bet-{uuid.uuid4().hex[:8]}"
    r = client.post(f"{API}/ingest", json=make_payload(ref))
    assert r.status_code == 201
    return ref


def selection_id(client, ref, period="ft", side="over"):
    for e in client.get(f"{API}/board").json()["events"]:
        if e["external_ref"] == ref and e["period"] == period and e["side"] == side:
            return e["selection_id"]
    raise AssertionError(f"no {period} {side} selection for {ref}")


def key():
    return f"k-{uuid.uuid4().hex[:12]}"


def hdr(extra=None):
    h = {"X-Bet-Token": TOKEN}
    if extra:
        h.update(extra)
    return h


@pytest.fixture
def client():
    with httpx.Client(timeout=10) as c:
        yield c


async def test_auth_required(client):
    ref = seed_event(client)
    sid = selection_id(client, ref)
    body = {"selection_id": sid, "stake": 50, "mode": "manual", "idempotency_key": key()}
    r = client.post(f"{API}/bets", json=body)
    assert r.status_code == 401
    r = client.post(f"{API}/bets", json=body, headers={"X-Bet-Token": "wrong"})
    assert r.status_code == 401
    r = client.get(f"{API}/bets")
    assert r.status_code == 401
    r = client.get(f"{API}/bridge/commands")
    assert r.status_code == 401


async def test_place_manual_flow(client):
    ref = seed_event(client)
    sid = selection_id(client, ref, period="ft", side="over")
    body = {"selection_id": sid, "stake": 50, "mode": "manual", "idempotency_key": key()}

    r = client.post(f"{API}/bets", json=body, headers=hdr())
    assert r.status_code == 201, r.text
    bet = r.json()
    assert bet["status"] == "requested"
    assert bet["odds_at_request"] == 1.85  # snapshot from v_current_odds
    assert bet["side"] == "over" and bet["line_value"] == 222.5
    assert bet["mode"] == "manual" and bet["stake"] == 50
    bet_id = bet["id"]

    # idempotent replay -> same bet, 200
    r = client.post(f"{API}/bets", json=body, headers=hdr())
    assert r.status_code == 200 and r.json()["id"] == bet_id

    # command appears for the pokerbet bridge
    cmds = client.get(f"{API}/bridge/commands?bookmaker=pokerbet", headers=hdr()).json()["commands"]
    cmd = next(c for c in cmds if c["bet_id"] == bet_id)
    assert cmd["side"] == "over" and cmd["line_value"] == 222.5
    assert cmd["odds_at_request"] == 1.85 and cmd["stake"] == 50
    assert cmd["home_team"] == "Lakers" and cmd["away_team"] == "Celtics"
    assert cmd["period"] == "ft" and cmd["market_type"] == "total_points"
    assert cmd["mode"] == "manual"

    # other bookmaker sees nothing
    other = client.get(f"{API}/bridge/commands?bookmaker=other", headers=hdr()).json()["commands"]
    assert all(c["bet_id"] != bet_id for c in other)

    # delivered -> confirmed
    r = client.post(f"{API}/bridge/report", json={"bet_id": bet_id, "status": "delivered"},
                    headers=hdr())
    assert r.status_code == 200 and r.json()["status"] == "delivered"
    cmds = client.get(f"{API}/bridge/commands?bookmaker=pokerbet", headers=hdr()).json()["commands"]
    assert all(c["bet_id"] != bet_id for c in cmds)  # no longer pending

    r = client.post(f"{API}/bridge/report", json={"bet_id": bet_id, "status": "confirmed"},
                    headers=hdr())
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert r.json()["confirmed_at"] is not None

    # list shows it
    bets = client.get(f"{API}/bets", headers=hdr()).json()["bets"]
    mine = next(b for b in bets if b["id"] == bet_id)
    assert mine["status"] == "confirmed"


async def test_cancel_and_invalid_transitions(client):
    ref = seed_event(client)
    sid = selection_id(client, ref, period="q1", side="under")

    r = client.post(f"{API}/bets", json={"selection_id": sid, "stake": 25,
                                         "mode": "manual", "idempotency_key": key()},
                    headers=hdr())
    bet_id = r.json()["id"]

    # invalid transition: confirmed straight from requested
    r = client.post(f"{API}/bridge/report", json={"bet_id": bet_id, "status": "confirmed"},
                    headers=hdr())
    assert r.status_code == 409

    # cancel from requested
    r = client.post(f"{API}/bets/{bet_id}/cancel", headers=hdr())
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    r = client.post(f"{API}/bets/{bet_id}/cancel", headers=hdr())
    assert r.status_code == 409  # already cancelled
    r = client.post(f"{API}/bets/999999/cancel", headers=hdr())
    assert r.status_code == 404

    # report on unknown bet
    r = client.post(f"{API}/bridge/report", json={"bet_id": 999999, "status": "failed"},
                    headers=hdr())
    assert r.status_code == 404

    # delivered -> failed with reason
    r = client.post(f"{API}/bets", json={"selection_id": sid, "stake": 25,
                                         "mode": "manual", "idempotency_key": key()},
                    headers=hdr())
    bid2 = r.json()["id"]
    client.post(f"{API}/bridge/report", json={"bet_id": bid2, "status": "delivered"}, headers=hdr())
    r = client.post(f"{API}/bridge/report",
                    json={"bet_id": bid2, "status": "failed", "reason": "odds moved"},
                    headers=hdr())
    assert r.status_code == 200 and r.json()["failed_reason"] == "odds moved"


async def test_validation_and_expiry(client):
    ref = seed_event(client)
    sid = selection_id(client, ref, period="q2", side="over")

    # zero stake / bad mode / short key
    for bad in (
        {"stake": 0}, {"stake": -5}, {"mode": "turbo"}, {"idempotency_key": "short"},
    ):
        body = {"selection_id": sid, "stake": 50, "mode": "manual", "idempotency_key": key()}
        body.update(bad)
        assert client.post(f"{API}/bets", json=body, headers=hdr()).status_code == 422

    # closed selection
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute("UPDATE selections SET is_open = false WHERE id = $1", sid)
    finally:
        await conn.close()
    body = {"selection_id": sid, "stake": 50, "mode": "manual", "idempotency_key": key()}
    r = client.post(f"{API}/bets", json=body, headers=hdr())
    assert r.status_code == 422 and "not found or not open" in r.text
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute("UPDATE selections SET is_open = true WHERE id = $1", sid)
    finally:
        await conn.close()

    # expiry: age a requested bet past the window, bridge sweep expires it
    r = client.post(f"{API}/bets", json={"selection_id": sid, "stake": 10,
                                         "mode": "manual", "idempotency_key": key()},
                    headers=hdr())
    bid = r.json()["id"]
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute(
            "UPDATE bets SET requested_at = now() - interval '30 minutes' WHERE id = $1", bid
        )
    finally:
        await conn.close()
    cmds = client.get(f"{API}/bridge/commands?bookmaker=pokerbet", headers=hdr()).json()["commands"]
    assert all(c["bet_id"] != bid for c in cmds)
    conn = await asyncpg.connect(DB_URL)
    try:
        status = await conn.fetchval("SELECT status FROM bets WHERE id = $1", bid)
        assert status == "expired"
    finally:
        await conn.close()
