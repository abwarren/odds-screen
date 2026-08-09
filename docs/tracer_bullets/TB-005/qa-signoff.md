# TB-005 QA Sign-Off — Realtime SSE Push

**Date:** 2026-08-10 | **Reviewer:** Hermes (vertical-slicing + tracer-bullets skills)

## Architecture — 🟢 Approved

- In-process pub/sub is the right shape for a single-worker wallboard API;
  Redis pub/sub noted as the Stage-3 scale-out path (same `notify` interface).
- SSE (not WebSockets): one-way server→client push, native EventSource in the
  browser, auto-reconnect — the minimal correct tool for "screen reflects
  odds changes fast".
- 15s keepalive keeps proxies from dropping idle connections; comment-only
  lines are spec-valid.

## Implementation — 🟢 Approved

- `notify()` uses `put_nowait` + drop-on-full — a slow subscriber can't block
  the ingest path.
- `/stream` sets `Cache-Control: no-cache` and `X-Accel-Buffering: no` (nginx
  buffering would defeat realtime).
- UI: EventSource wired to `tick()`; reconnect with backoff; 5s poll kept as
  fallback so a dropped stream can't freeze the board.

## Verification — 🟢 Approved

- Live loopback: 23/23 tests pass (2 new SSE tests).
- Live demo (evidence/sse-demo.log): subscriber receives `snapshot` then
  `ingest` immediately after a POST /ingest — realtime push proven end-to-end.

## Production Readiness — 🟡 Approved with Conditions

- ✅ Works now on the single-worker docker-compose stack.
- ⚠️ Condition: multi-worker deployments must move to Redis pub/sub (or pin
  workers=1). Tracked in SESSION_HANDOFF.
- ⚠️ Condition: EventSource in the browser auto-reconnects, but if the API is
  behind a proxy the proxy must allow streaming (no buffering).

## Overall: 🟢 APPROVED (with conditions)

TB-005's realtime push is validated with evidence. The screen now updates the
moment odds change — the poll fallback keeps it correct if the stream drops.
