"""Live loopback tests for cross-book comparison (TB-004).

Hits the REAL stack (api:8002, db:5434). Verifies the multi-book registry,
the v_matched_events grouping, per-book lines/odds in /compare, best-odds
flags per side, and period filtering.

NOTE: uses unique team names (Heat/Nuggets, Knicks/Nets) so other tests'
Lakers/Celtics fixtures never pollute these assertions.
"""
import uuid

import httpx
import pytest

API = "http://localhost:8002"

LIVE_EVENT = {
    "status": "live", "period_code": "q3", "clock_seconds": 420,
    "home_score": 72, "away_score": 68,
}

ALL_BOOK_CODES = {
    "easybet", "sportingbet", "pokerbet", "wsb", "goldrush", "sunbet",
    "hollywoodbets", "betway", "gbets", "10bet", "playabets", "lulabet",
    "yesplay", "bettabets", "supabets",
}


def ingest(client, book: str, ref: str, home: str, away: str, markets: list[dict]):
    r = client.post(f"{API}/ingest", json={
        "bookmaker": book,
        "event": {"external_ref": ref, "competition": "NBA", "sport": "basketball",
                  "home_team": home, "away_team": away, **LIVE_EVENT},
        "markets": markets,
    })
    assert r.status_code == 201, r.text


def ou(line, over, under):
    return {"selections": [
        {"side": "over", "line_value": line, "odds": over},
        {"side": "under", "line_value": line, "odds": under},
    ]}


@pytest.fixture
def client():
    with httpx.Client(timeout=10) as c:
        yield c


def test_books_registry(client):
    books = client.get(f"{API}/books").json()["books"]
    codes = {b["code"] for b in books}
    assert ALL_BOOK_CODES <= codes  # all 15 Chrome-folder books registered
    pokerbet = next(b for b in books if b["code"] == "pokerbet")
    assert pokerbet["platform_type"] == "betconstruct"


def test_compare_groups_same_game_across_books(client):
    # three books, same game (Heat vs Nuggets), distinct FT lines/odds
    ingest(client, "pokerbet", f"cmp-{uuid.uuid4().hex[:8]}", "Heat", "Nuggets",
           [{"period": "ft", "market_type": "total_points", "status": "open",
             **ou(222.5, 1.85, 1.90)}])
    ingest(client, "hollywoodbets", f"cmp-{uuid.uuid4().hex[:8]}", "Heat", "Nuggets",
           [{"period": "ft", "market_type": "total_points", "status": "open",
             **ou(222.5, 1.80, 1.85)}])
    ingest(client, "betway", f"cmp-{uuid.uuid4().hex[:8]}", "Heat", "Nuggets",
           [{"period": "ft", "market_type": "total_points", "status": "open",
             **ou(223.5, 1.90, 1.70)}])

    matches = client.get(f"{API}/compare?period=ft").json()["matches"]
    mine = [m for m in matches if m["home_team"] == "Heat" and m["away_team"] == "Nuggets"]
    assert len(mine) == 1
    m = mine[0]

    # all three books grouped into ONE match, same match_id
    assert set(m["books"]) == {"pokerbet", "hollywoodbets", "betway"}
    assert m["books"]["pokerbet"]["over"] == {"line": 222.5, "odds": 1.85}
    assert m["books"]["pokerbet"]["under"] == {"line": 222.5, "odds": 1.90}
    assert m["books"]["hollywoodbets"]["over"] == {"line": 222.5, "odds": 1.80}
    assert m["books"]["betway"]["over"] == {"line": 223.5, "odds": 1.90}
    assert m["books"]["betway"]["under"] == {"line": 223.5, "odds": 1.70}

    # best per side: over -> betway 1.90, under -> pokerbet 1.90
    assert m["best"]["over"] == {"book": "betway", "odds": 1.90, "line": 223.5}
    assert m["best"]["under"] == {"book": "pokerbet", "odds": 1.90, "line": 222.5}


def test_compare_period_filter_and_unmatched(client):
    # Heat/Nuggets already exist (prior test); add q1 data only for betway
    ingest(client, "betway", f"cmp-{uuid.uuid4().hex[:8]}", "Heat", "Nuggets",
           [{"period": "q1", "market_type": "total_points", "status": "open",
             **ou(52.5, 1.75, 2.05)}])
    # unrelated game -> its own match
    ingest(client, "pokerbet", f"cmp-{uuid.uuid4().hex[:8]}", "Knicks", "Nets",
           [{"period": "ft", "market_type": "total_points", "status": "open",
             **ou(210.5, 1.90, 1.80)}])

    matches = client.get(f"{API}/compare?period=q1").json()["matches"]
    heat = [m for m in matches if m["home_team"] == "Heat"][0]
    assert set(heat["books"]) == {"betway"}  # only the book with q1 data
    assert heat["books"]["betway"]["over"] == {"line": 52.5, "odds": 1.75}

    matches = client.get(f"{API}/compare?period=ft").json()["matches"]
    knicks = [m for m in matches if m["home_team"] == "Knicks"]
    assert len(knicks) == 1 and set(knicks[0]["books"]) == {"pokerbet"}


def test_compare_moneyline(client):
    # moneyline on Heat/Nuggets (seeded): home/away sides, no line, best per side
    matches = client.get(f"{API}/compare?period=ft&market_type=moneyline").json()["matches"]
    heat = [m for m in matches if m["home_team"] == "Heat" and m["away_team"] == "Nuggets"]
    assert len(heat) == 1
    m = heat[0]
    assert set(m["books"]) == {"pokerbet", "hollywoodbets"}
    assert m["books"]["pokerbet"]["home"] == {"line": None, "odds": 1.95}
    assert m["books"]["pokerbet"]["away"] == {"line": None, "odds": 1.85}
    assert m["books"]["hollywoodbets"]["home"] == {"line": None, "odds": 1.80}
    assert m["books"]["hollywoodbets"]["away"] == {"line": None, "odds": 2.00}
    assert m["best"]["home"] == {"book": "pokerbet", "odds": 1.95, "line": None}
    assert m["best"]["away"] == {"book": "hollywoodbets", "odds": 2.00, "line": None}
    assert set(m["best"]) == {"home", "away"}  # no over/under keys for a moneyline


def test_compare_empty(client):
    # no data for the spread market type -> no matches, no error
    matches = client.get(f"{API}/compare?period=ft&market_type=spread").json()["matches"]
    assert matches == []
