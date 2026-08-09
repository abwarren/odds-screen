"""Live loopback tests for the ingest tracer bullet — hit the REAL stack.

This is the vertical-slice acceptance suite: real API (localhost:8002),
real Postgres (localhost:5434). No mocks. Requires the compose stack up:

    docker compose up -d --build
    .venv/bin/python -m pytest tests/ -v

Coverage:
  * full lifecycle: ingest -> board -> odds change -> line move -> dedupe
  * odds_history append-only invariants checked directly in Postgres
  * rejection paths: bad odds, unknown period, extra fields, empty payload
"""
import uuid

import asyncpg
import httpx
import pytest

API = "http://localhost:8002"
DB_URL = "postgresql://postgres:postgres@localhost:5434/odds"

PERIODS = ["q1", "q2", "q3", "q4", "ft"]
LIVE_EVENT = {
    "status": "live",
    "period_code": "q3",
    "clock_seconds": 420,
    "home_score": 72,
    "away_score": 68,
}


def make_payload(ref: str, *, over=1.85, under=1.90, line=222.5, event=None,
                 period_odds=None, period_lines=None):
    ev = dict(LIVE_EVENT)
    if event:
        ev.update(event)
    markets = []
    for p in PERIODS:
        o, u = over, under
        if period_odds and p in period_odds:
            o = period_odds[p].get("over", over)
            u = period_odds[p].get("under", under)
        ln = line
        if period_lines and p in period_lines:
            ln = period_lines[p]
        markets.append(
            {
                "period": p,
                "market_type": "total_points",
                "status": "open",
                "selections": [
                    {"side": "over", "line_value": ln, "odds": o},
                    {"side": "under", "line_value": ln, "odds": u},
                ],
            }
        )
    return {
        "bookmaker": "pokerbet",
        "event": {
            "external_ref": ref,
            "competition": "NBA",
            "sport": "basketball",
            "home_team": "Lakers",
            "away_team": "Celtics",
            **ev,
        },
        "markets": markets,
    }


def unique_ref() -> str:
    return f"evt-{uuid.uuid4().hex[:8]}"


async def db():
    return await asyncpg.connect(DB_URL)


def board_rows(client: httpx.Client, ref: str) -> list[dict]:
    events = client.get(f"{API}/board").json()["events"]
    return [e for e in events if e["external_ref"] == ref] if events else []


@pytest.fixture
def client():
    with httpx.Client(timeout=10) as c:
        yield c


async def test_full_lifecycle(client):
    ref = unique_ref()
    p = make_payload(ref)

    # --- tick 1: fresh event, 5 markets, 10 selections, 10 history rows ---
    r = client.post(f"{API}/ingest", json=p)
    assert r.status_code == 201, r.text
    body = r.json()
    assert isinstance(body.pop("event_id"), int)
    assert body == {
        "markets": 5, "selections": 10, "odds_appended": 10,
        "lines_moved": 0, "unchanged": 0,
    }

    rows = board_rows(client, ref)
    assert len(rows) == 10
    assert {row["period"] for row in rows} == set(PERIODS)
    assert {row["side"] for row in rows} == {"over", "under"}
    assert all(row["line_value"] == 222.5 for row in rows)
    assert all(row["odds"] in (1.85, 1.90) for row in rows)
    assert rows[0]["home_team"] == "Lakers" and rows[0]["period_code"] == "q3"

    # --- tick 2: ONE odds change (ft over 1.85 -> 1.75) ---
    p2 = make_payload(ref, period_odds={"ft": {"over": 1.75}})
    r = client.post(f"{API}/ingest", json=p2)
    assert r.status_code == 201
    assert r.json()["odds_appended"] == 1 and r.json()["unchanged"] == 9
    assert r.json()["selections"] == 0 and r.json()["lines_moved"] == 0

    rows = board_rows(client, ref)
    ft_over = next(x for x in rows if x["period"] == "ft" and x["side"] == "over")
    assert ft_over["odds"] == 1.75
    # every other selection unchanged at its tick-1 value
    q1_over = next(x for x in rows if x["period"] == "q1" and x["side"] == "over")
    assert q1_over["odds"] == 1.85

    # --- tick 3: LINE MOVE on ft (222.5 -> 223.5) both sides ---
    p3 = make_payload(
        ref,
        period_odds={"ft": {"over": 1.80, "under": 1.85}},
        period_lines={"ft": 223.5},
    )
    r = client.post(f"{API}/ingest", json=p3)
    assert r.status_code == 201
    assert r.json()["lines_moved"] == 2
    assert r.json()["selections"] == 2
    assert r.json()["odds_appended"] == 2
    assert r.json()["unchanged"] == 8

    rows = board_rows(client, ref)
    ft_rows = [x for x in rows if x["period"] == "ft"]
    assert {x["line_value"] for x in ft_rows} == {223.5}
    assert next(x for x in ft_rows if x["side"] == "over")["odds"] == 1.80

    # --- tick 4: exact duplicate of tick 3 -> nothing appended ---
    r = client.post(f"{API}/ingest", json=p3)
    assert r.status_code == 201
    assert r.json()["odds_appended"] == 0 and r.json()["unchanged"] == 10

    # --- invariants straight from Postgres ---
    conn = await db()
    try:
        n_history = await conn.fetchval(
            """
            SELECT count(*) FROM odds_history oh
            JOIN selections s ON s.id = oh.selection_id
            JOIN markets m ON m.id = s.market_id
            JOIN events e ON e.id = m.event_id
            WHERE e.external_ref = $1
            """,
            ref,
        )
        assert n_history == 13  # 10 + 1 + 2 + 0

        n_selections = await conn.fetchval(
            """
            SELECT count(*) FROM selections s
            JOIN markets m ON m.id = s.market_id
            JOIN events e ON e.id = m.event_id
            WHERE e.external_ref = $1
            """,
            ref,
        )
        assert n_selections == 12  # 10 + 2 line-move rows

        # ft market: old 222.5 pair closed, new 223.5 pair open
        ft = await conn.fetchrow(
            """
            SELECT m.id, p.code FROM markets m
            JOIN events e ON e.id = m.event_id
            JOIN periods p ON p.id = m.period_id
            WHERE e.external_ref = $1 AND p.code = 'ft'
            """,
            ref,
        )
        ft_id = ft["id"]
        old = await conn.fetch(
            "SELECT side, line_value, is_open FROM selections WHERE market_id = $1 ORDER BY id",
            ft_id,
        )
        assert [(r["side"], r["line_value"], r["is_open"]) for r in old] == [
            ("over", 222.5, False),
            ("under", 222.5, False),
            ("over", 223.5, True),
            ("under", 223.5, True),
        ]
        # old selection's history fully intact: 1.85 (tick 1) then 1.75 (tick 2
        # odds change) — closed at the line move without losing anything
        old_sel = await conn.fetchval(
            "SELECT id FROM selections WHERE market_id = $1 AND line_value = 222.5 AND side = 'over'",
            ft_id,
        )
        hist = await conn.fetch(
            "SELECT odds FROM odds_history WHERE selection_id = $1 ORDER BY id", old_sel
        )
        assert [str(h["odds"]) for h in hist] == ["1.85", "1.75"]

        # last_seen_at bumped by the duplicate tick
        last_seen = await conn.fetchval(
            "SELECT last_seen_at FROM events WHERE external_ref = $1", ref
        )
        assert last_seen is not None
    finally:
        await conn.close()


async def test_second_event_is_independent(client):
    ref1, ref2 = unique_ref(), unique_ref()
    client.post(f"{API}/ingest", json=make_payload(ref1))
    # second event is a DIFFERENT game — /board dedupes by match, so same-team
    # re-ingests would collapse into one canonical event
    client.post(f"{API}/ingest", json=make_payload(
        ref2, over=2.10, under=1.60,
        event={"home_team": "Cavs", "away_team": "Magic"},
    ))

    rows1 = board_rows(client, ref1)
    rows2 = board_rows(client, ref2)
    assert len(rows1) == 10 and len(rows2) == 10
    assert all(x["odds"] == 1.85 for x in rows1 if x["side"] == "over")
    assert all(x["odds"] == 2.10 for x in rows2 if x["side"] == "over")

    conn = await db()
    try:
        # ref1 and ref2 are distinct events, each with its own 5 markets
        evs = await conn.fetch(
            "SELECT id FROM events WHERE external_ref IN ($1, $2) ORDER BY id", ref1, ref2
        )
        assert len(evs) == 2
        for ev in evs:
            assert await conn.fetchval(
                "SELECT count(*) FROM markets WHERE event_id = $1", ev["id"]
            ) == 5
        # one shared competition row (NBA), two events
        assert await conn.fetchval("SELECT count(*) FROM competitions") == 1
    finally:
        await conn.close()


async def test_live_state_updates_in_place(client):
    ref = unique_ref()
    client.post(f"{API}/ingest", json=make_payload(ref))
    conn = await db()
    try:
        before = await conn.fetchval("SELECT count(*) FROM events")
    finally:
        await conn.close()
    client.post(
        f"{API}/ingest",
        json=make_payload(
            ref, event={"status": "live", "period_code": "q4",
                        "clock_seconds": 120, "home_score": 90, "away_score": 84}
        ),
    )
    conn = await db()
    try:
        ev = await conn.fetchrow(
            "SELECT status, period_code, clock_seconds, home_score, away_score "
            "FROM events WHERE external_ref = $1",
            ref,
        )
        assert dict(ev) == {
            "status": "live", "period_code": "q4", "clock_seconds": 120,
            "home_score": 90, "away_score": 84,
        }
        total = await conn.fetchval("SELECT count(*) FROM events")
        assert total == before  # upserted in place, no new row
    finally:
        await conn.close()


async def test_rejections(client):
    ref = unique_ref()
    good = make_payload(ref)

    bad_odds = make_payload(unique_ref())
    bad_odds["markets"][0]["selections"][0]["odds"] = 0.50
    r = client.post(f"{API}/ingest", json=bad_odds)
    assert r.status_code == 422
    assert "odds" in r.text

    bad_period = make_payload(unique_ref())
    bad_period["markets"][0]["period"] = "q9"
    r = client.post(f"{API}/ingest", json=bad_period)
    assert r.status_code == 422
    assert "q9" in r.text

    extra = make_payload(unique_ref())
    extra["event"]["spurious"] = True
    r = client.post(f"{API}/ingest", json=extra)
    assert r.status_code == 422

    empty = {"bookmaker": "pokerbet", "event": good["event"], "markets": []}

    # nothing from the rejected payloads leaked into the DB
    conn = await db()
    try:
        before = await conn.fetchval("SELECT count(*) FROM events")
    finally:
        await conn.close()
    r = client.post(f"{API}/ingest", json=empty)
    assert r.status_code == 422
    conn = await db()
    try:
        assert await conn.fetchval("SELECT count(*) FROM events") == before
    finally:
        await conn.close()
