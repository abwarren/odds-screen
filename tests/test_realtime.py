"""Live loopback tests for the SSE realtime stream (TB-005)."""
import asyncio
import json
import uuid

import httpx
import pytest

API = "http://localhost:8002"

PERIODS = ["q1", "q2", "q3", "q4", "ft"]


def make_payload(ref, over=1.85, under=1.90, home="Spurs", away="Mavs"):
    return {
        "bookmaker": "pokerbet",
        "event": {"external_ref": ref, "competition": "NBA", "sport": "basketball",
                  "home_team": home, "away_team": away,
                  "status": "live", "period_code": "q3", "clock_seconds": 420,
                  "home_score": 72, "away_score": 68},
        "markets": [
            {"period": p, "market_type": "total_points", "status": "open",
             "selections": [
                 {"side": "over", "line_value": 222.5, "odds": over},
                 {"side": "under", "line_value": 222.5, "odds": under},
             ]}
            for p in PERIODS
        ],
    }


@pytest.fixture
def client():
    with httpx.Client(timeout=10) as c:
        yield c


@pytest.fixture
async def aclient():
    async with httpx.AsyncClient(timeout=20) as c:
        yield c


async def test_sse_receives_ingest_event(client, aclient):
    ref = f"rt-{uuid.uuid4().hex[:8]}"

    # open the stream (httpx reads lines; collect events for ~4s)
    events = []
    async with aclient.stream("GET", f"{API}/stream") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        done = asyncio.get_event_loop().create_future()

        async def reader():
            try:
                async for line in resp.aiter_lines():
                    if line.startswith("event: "):
                        events.append(line.split(":", 1)[1].strip())
                    if len(events) >= 2:
                        break
            finally:
                if not done.done():
                    done.set_result(True)

        task = asyncio.create_task(reader())
        await asyncio.sleep(1)  # let the snapshot ping arrive
        client.post(f"{API}/ingest", json=make_payload(ref))
        await asyncio.wait_for(done, timeout=8)
        await task

    assert "snapshot" in events
    assert "ingest" in events  # pushed the moment the tick landed


async def test_sse_keepalive_without_events(aclient):
    # no ingest -> stream still emits keepalive comments (connection alive)
    got = []
    async with aclient.stream("GET", f"{API}/stream") as resp:
        async for line in resp.aiter_lines():
            if line.startswith(":"):
                got.append(line)
            if len(got) >= 1:
                break
    assert got and got[0].startswith(": keepalive")
