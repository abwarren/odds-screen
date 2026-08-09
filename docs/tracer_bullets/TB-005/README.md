# TB-005 — Realtime SSE Push

**Status:** ✅ PASSED (C2 — demonstrated, tests green)
**Date:** 2026-08-10
**Repo:** github.com/abwarren/odds-screen

## What Was Demonstrated

Slow-moving markets should update on the screen the INSTANT a scrape tick
lands, not on the next 5s poll. This slice adds SSE push: any `/ingest` tick
notifies every connected subscriber, and the UI re-fetches the changed
projection. The 5s poll remains as a reconnect fallback.

| Layer | What it proves |
|---|---|
| Pub/Sub | `realtime.py` — in-process `notify(topic)` → per-subscriber queue; slow subscribers dropped (backpressure) |
| SSE endpoint | `GET /stream` — `text/event-stream`, snapshot ping on connect, 15s keepalive comments, `X-Accel-Buffering: no` |
| Trigger | `/ingest` calls `realtime.notify("ingest")` after a successful tick |
| UI | `EventSource("/stream")` — `ingest`/`snapshot` events call `tick()` (re-fetch board/bets/compare); `onerror` auto-reconnects every 5s; 5s interval poll kept as fallback |

## Live Demo (evidence/sse-demo.log)

```
event: snapshot        <- on connect
data: {}
event: ingest           <- the instant the tick landed
data: {}
```

A subscriber connected, then a `POST /ingest` was issued — the `ingest` event
arrived immediately.

## Automated Tests (23 passed total; 2 new)

- `test_sse_receives_ingest_event` — opens the stream (asserts 200 +
  `text/event-stream`), ingests, asserts both `snapshot` and `ingest` arrive.
- `test_sse_keepalive_without_events` — no ticks → keepalive comment still
  emitted (connection alive).

## Capability Levels

| Capability | Level |
|---|---|
| SSE push (ingest → subscribers) | C3 (QA verified) |
| UI realtime consumption | C2 (demonstrated — EventSource wired, poll fallback) |
| Cross-worker scale-out (Redis) | C0 (designed — noted for Stage 3) |

## Critical Discoveries

- **Single-worker assumption.** The pub/sub registry is in-process — one
  uvicorn worker. Multi-worker deployments need Redis pub/sub (documented).
- **Backpressure.** A subscriber that stops draining its queue gets dropped
  rather than blocking `notify` — the wallboard must re-fetch on reconnect
  (it does: snapshot ping + full tick()).

## Files

```
backend/app/realtime.py        NEW — pub/sub + SSE generator
backend/app/main.py            MOD — /stream route; /ingest notifies
web/bets.html                  MOD — EventSource subscription (poll fallback kept)
tests/test_realtime.py         NEW — 2 SSE tests
docs/tracer_bullets/TB-005/    NEW — this doc + evidence/
```

## Note on "all 19 books"

The Chrome 'Books' folder's 19 entries resolve to **15 unique books** — the
other 4 entries are Google-search links for hollywoodbets/betway/gbets (all
already registered) plus an easybet terms page and the sa20 league site.
The registry is complete at 15. The remaining work to fill every book's
column with live data is the per-book scrapers (next slices).
