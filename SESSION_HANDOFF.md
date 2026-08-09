# SESSION_HANDOFF — Odds Screen

## CURRENT OBJECTIVE
Build the odds screen (live SA bookmaker basketball totals wallboard) in
vertical slices. TB-001 (ingest path) and TB-003 (remote bet placement) are
complete; next is TB-002 (real BetConstruct scraper, Phase C of the plan).

## LOCKED REQUIREMENTS
- v1: live basketball ONLY, Total Points O/U markets only (q1, q2, q3, q4, ft).
- Stack: FastAPI + asyncpg + PostgreSQL 16 (Docker Compose, mapped ports
  db:5434 / api:8002), vanilla JS/SVG wallboard (no Chart.js).
- Data source v1: PokerBet.co.za (BetConstruct) DOM scraping, ~20s cadence.
- Bet placement from the screen IS IN SCOPE (user request, TB-003): bets are
  delivered to the user's OWN logged-in PokerBet session via a browser bridge.
  Default = slip-populate + MANUAL confirm on PokerBet; auto-confirm is an
  explicit per-bet opt-in that re-verifies slip odds before placing.
- Generic schema — markets/books/sports are new ROWS, never schema changes.
- 15 SA books staged for later (Chrome 'Books' folder; creds in user's
  password manager, added manually).

## SYSTEM STATE
- Compose stack RUNNING: postgres:16 (5434), api (8002). Both healthy.
- API v0.3.0: /health, /board (now incl. selection_id), /ingest, /bets*,
  /bridge/commands, /bridge/report, /bets-ui.
- DB: `bets` table applied live (schema.sql). Lifecycle requested → delivered
  → confirmed | failed; requested → cancelled | failed | expired
  (BET_EXPIRY_MINUTES=15, swept lazily on bridge poll).
- Auth: all money routes require X-Bet-Token; BET_TOKEN in docker-compose
  (dev default 'dev-token-change-me'); unset ⇒ 503 (default-closed).
- Test venv: repo `.venv` (pytest, pytest-asyncio, httpx, asyncpg, playwright).
- Repo: github.com/abwarren/odds-screen, branch main, local == origin.

## COMPLETED SLICE
TB-003 — remote bet placement from the odds screen: bets API with
server-side odds snapshot + idempotency-key replay, strict lifecycle state
machine, /bridge/commands + /bridge/report, browser-side overlay
(overlay-core.js + Tampermonkey userscript) filling the slip in the user's own
logged-in PokerBet session, dark control page (bets.html). QA approved 🟢
with conditions (see KNOWN ISSUES).

## FILES CHANGED (TB-003)
- db/schema.sql — bets table (applied live)
- backend/app/schemas.py — BetIn, BridgeReportIn
- backend/app/bets.py — place/cancel/report/commands/list_bets
- backend/app/main.py — /bets*, /bridge/*, /bets-ui; X-Bet-Token guard
- web/bets.html — control page (board + stake + bets table)
- bridge/overlay-core.js — pure-DOM bridge core (OddsScreenBridge)
- bridge/tampermonkey/odds-screen-bet-bridge.user.js — pokerbet.co.za userscript
- docker-compose.yml — repo-root build context; BET_TOKEN, BET_EXPIRY_MINUTES
- tests/test_bets.py, tests/test_overlay_harness.py
- scripts/demo_tb003.py — demo walkthrough
- docs/tracer_bullets/TB-003/{README,qa-signoff,evidence/} — evidence

## TESTS & RESULTS
`.venv/bin/python -m pytest tests/ -v` → 16 passed (4 ingest + 4 bets + 8
overlay harness), live loopback, no mocks.
Log: docs/tracer_bullets/TB-003/evidence/test-results.log

## CRITICAL DISCOVERIES
- Idempotency-key replay: same key ⇒ 200 + original bet (201 on first create)
  — the key IS the dedupe; protects double-clicks and bridge retries.
- Odds must be snapshotted server-side (v_current_odds at request time) —
  client-supplied odds would let a stale screen place at a phantom price.
- Explicit transition map (_ALLOWED) — illegal transitions are 409s.
- Stale bets swept lazily on bridge poll (no cron) — expiry is
  eventually-consistent by design, BET_EXPIRY_MINUTES=15.
- Playwright harness pitfalls: page.evaluate params named arguments/args
  collide with the wrapper; expose_function needs plain serializable closures.

## KNOWN ISSUES
- BET_TOKEN dev default ('dev-token-change-me') MUST change before real money.
- Overlay core is C2 (harness-verified, fixture DOM), not C3 until run against
  the real logged-in PokerBet page.
- Bridge is browser-side — placement requires a browser logged into
  pokerbet.co.za on the machine; manual mode needs the human to click Place Bet.
- overlay-core.js loaded via @require file:// in dev — bundle for release.
- POST /ingest still unauthenticated (TB-001 known issue, still open).
- No rate limit / payload cap on /ingest yet.

## NEXT VERTICAL SLICE
TB-002 — BetConstruct scraper (Phase C, plan tasks 10–15): Playwright service
that polls PokerBet live basketball, extracts game state + totals markets
(DOM map in betconstruct-sportsbook-scraping skill), normalizes to the TB-001
contract, POSTs to /ingest. Slices: skeleton → event extraction → market
extraction → payload → poll loop (~20s, resilience). Then wallboard Phase D
embeds the TB-003 bet control UI.

## FIRST ACTION ON RESUME
cd ~/projects/odds-screen && docker compose ps && curl -s http://localhost:8002/health
