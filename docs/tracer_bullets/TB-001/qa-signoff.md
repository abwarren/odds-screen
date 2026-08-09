# TB-001 QA Sign-Off — Live Basketball Totals Ingest Path

**Date:** 2026-08-09 | **Reviewer:** Hermes (vertical-slicing + tracer-bullets skills)

## Architecture — 🟢 Approved

- Generic market/period model per schema.sql: any sport/market/book adds rows,
  not schema changes. Confirmed by the second-event test (shared competition,
  independent events).
- Append-only `odds_history` + closed-selection semantics: line move closes the
  old row and starts a new one — CLV/+EV derivations remain possible.
- Screen read model (`v_current_odds` view + `/board` filtering `is_open`)
  matches the plan's "one query per poll" requirement.
- Ingest is all-or-nothing (single transaction) — no partial states.

## Implementation — 🟢 Approved

- Contract rejects unknown fields (`extra="forbid`) and bad values (odds ≥ 1.01,
  clock ≤ 3600, non-negative scores) at the boundary.
- Upserts keyed on natural keys (bookmaker code, sport code, sport+competition,
  bookmaker+external_ref, event+period+market_type, market+book+side+line).
- Dedupe compares Decimal-to-Decimal (scale-insensitive) — the float trap is
  documented in the code and pinned by tests.
- `/board` shows only open selections; closed line rows remain queryable via
  the view for analytics.

## Verification — 🟢 Approved

- Live loopback: 4/4 tests pass against the real running stack
  (localhost:8002 API, localhost:5434 Postgres) — no mocks.
- Demo log shows the full lifecycle: 10 rows → 1 odds change → 2 line-move
  rows → duplicate dedupe → 13 history rows, 12 selections, board consistent
  at every step (evidence/demo.log).
- Rejection paths verified: 422s and zero DB leakage.

## Production Readiness — 🟡 Approved with Conditions

- ✅ Works end-to-end, deployable via existing docker-compose.
- ⚠️ Condition: `POST /ingest` is unauthenticated — fine for local/single-host
  v1 (same trust domain as the scraper), but Stage 2+ (multi-book, remote
  scrapers) needs a shared token. Tracked in SESSION_HANDOFF known issues.
- ⚠️ Condition: no rate limiting / payload size cap on /ingest yet.

## Overall: 🟢 APPROVED

TB-001's architecture and implementation are validated with evidence. The
next vertical slice (TB-002, real BetConstruct scraper) may proceed.
