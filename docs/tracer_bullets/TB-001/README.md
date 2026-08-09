# TB-001 — Live Basketball Totals Ingest Path

**Status:** ✅ PASSED (C2 — demonstrated, automated tests green)
**Date:** 2026-08-09
**Repo:** github.com/abwarren/odds-screen

## What Was Demonstrated

The first vertical slice of the odds screen: **one live basketball game through
the full ingest path** — normalized payload → `POST /ingest` → Postgres upserts
→ append-only `odds_history` → `GET /board` read model. This is the tracer
bullet for the architecture: it validates every integration point (contract,
upsert logic, line-move semantics, dedupe, read model) before any scraper or
UI work begins.

| Layer | What it proves |
|---|---|
| Contract | Pydantic `IngestPayload` — normalized, bookmaker-agnostic, extra-field-rejecting |
| Ingest API | `POST /ingest` — all-or-nothing transaction, 422 on bad input |
| Postgres | Upserts by natural key; line move ⇒ new selection row, old row closed |
| History | Append-only — one row per odds change, dedupe on identical ticks |
| Screen API | `GET /board` — live events × open selections, one query |

## Lifecycle Demonstrated (evidence/demo.log)

1. **Tick 1** — fresh event, 5 markets (q1–q4, ft) × 2 selections = 10 rows,
   10 history rows. Board shows all 5 O/U markets.
2. **Tick 2** — ft OVER odds 1.85 → 1.75: 1 history row appended, 9 unchanged.
   Board reflects the new odds.
3. **Tick 3** — ft line move 222.5 → 223.5: old pair closed (`is_open=false`),
   2 new selection rows, 2 history rows. Board shows only the open 223.5 line.
4. **Tick 4** — exact duplicate: 0 appends, 10 unchanged. `last_seen_at` bumps.

## Automated Tests (evidence/test-results.log)

```
4 passed in 0.64s
```

- `test_full_lifecycle` — the 4-tick lifecycle above + Postgres invariants
  (13 history rows, 12 selections, old-line closed, old history intact).
- `test_second_event_is_independent` — two events coexist; shared competition.
- `test_live_state_updates_in_place` — score/clock/period upsert, no new row.
- `test_rejections` — odds < 1.01, unknown period, extra fields, empty markets
  → 422, nothing leaks into the DB.

## Capability Levels

| Capability | Level |
|---|---|
| Ingest contract + upsert path | C3 (QA verified) |
| Odds history append-only dedupe | C3 (QA verified) |
| Line-move selection lifecycle | C3 (QA verified) |
| Board read model (live, open selections) | C2 (demonstrated) |
| Real DOM scraper (PokerBet) | C0 (designed — Phase C) |
| Wallboard UI | C0 (designed — Phase D) |

## Critical Discovery

**Decimal-vs-float comparison defeats dedupe.** `numeric(6,2)` returns
`Decimal` from asyncpg; `Decimal('1.90') == 1.9` is **False** in Python
(exact-value comparison), so every identical tick was appended. Fix:
normalize incoming floats to `Decimal(str(x))` before comparing/inserting
(`_dec()` in `backend/app/ingest.py`). The test suite pins this behavior —
the lifecycle test would fail if dedupe regressed.

## Files

```
backend/app/schemas.py          NEW  — ingest contract (Pydantic)
backend/app/ingest.py           NEW  — upsert + dedupe + line-move service
backend/app/main.py             MOD  — POST /ingest route, /board is_open filter
tests/test_ingest.py            NEW  — live loopback acceptance suite
scripts/demo_tb001.py           NEW  — reproducible demo walkthrough
docs/tracer_bullets/TB-001/     NEW  — this doc + evidence/
```

## Next Vertical Slice

**TB-002 — Scraper stub → real BetConstruct DOM extraction (Phase C).**
The scraper service that polls PokerBet.co.za (~20s), normalizes the DOM into
the ingest contract, and POSTs to `/ingest`. The contract proven in TB-001 is
the scraper's output spec. See `betconstruct-sportsbook-scraping` skill for
the DOM map (event list rows, Match/Quarters tabs).
