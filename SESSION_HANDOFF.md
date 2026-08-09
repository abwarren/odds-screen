# SESSION_HANDOFF — Odds Screen

## CURRENT OBJECTIVE
Build the odds screen (live SA bookmaker basketball totals wallboard) in
vertical slices. TB-001 (ingest path) is complete; next is TB-002 (real
BetConstruct scraper, Phase C of the plan).

## LOCKED REQUIREMENTS
- v1: live basketball ONLY, Total Points O/U markets only (q1, q2, q3, q4, ft).
- Stack: FastAPI + asyncpg + PostgreSQL 16 (Docker Compose, mapped ports
  db:5434 / api:8002), vanilla JS/SVG wallboard (no Chart.js).
- Data source v1: PokerBet.co.za (BetConstruct) DOM scraping, ~20s cadence.
- Never auto-place bets. Screen is read-only display.
- Generic schema — markets/books/sports are new ROWS, never schema changes.
- 15 SA books staged for later (Chrome 'Books' folder; creds in user's
  password manager, added manually).

## SYSTEM STATE
- Compose stack RUNNING: postgres:16 (5434), api (8002). Both healthy.
- DB clean at commit time (demo data truncated post-run — tests recreate it).
- API v0.2.0: GET /health, GET /board (live events × open selections),
  POST /ingest (201; 422 on contract/period/market-type errors).
- Test venv: repo `.venv` (pytest, pytest-asyncio, httpx, asyncpg).
- Repo: github.com/abwarren/odds-screen, branch main, local == origin.

## COMPLETED SLICE
TB-001 — one live game through the ingest path end-to-end:
ingest contract → upserts → append-only history (dedupe) → line-move
selection lifecycle → /board read model. QA approved 🟢.

## FILES CHANGED (TB-001)
- backend/app/schemas.py — ingest contract (Pydantic, extra=forbid)
- backend/app/ingest.py — service: upserts, dedupe, line moves
- backend/app/main.py — POST /ingest; /board is_open filter + external_ref
- tests/test_ingest.py — 4 live-loopback acceptance tests
- scripts/demo_tb001.py — reproducible demo
- docs/tracer_bullets/TB-001/{README,qa-signoff,evidence/} — evidence
- .gitignore, pytest.ini

## TESTS & RESULTS
`.venv/bin/python -m pytest tests/ -v` → 4 passed in 0.64s (live loopback).
Demo: scripts/demo_tb001.py → evidence/demo.log (full lifecycle).

## CRITICAL DISCOVERIES
- Decimal-vs-float equality is False in Python (`Decimal('1.90') == 1.9`).
  Dedupe MUST normalize to Decimal(str(x)) — see `_dec()` in ingest.py.
  Pinned by the lifecycle test.
- /board must filter `s.is_open` — the view itself returns closed (old-line)
  selections too; the wallboard only wants current lines.
- asyncpg returns numeric as Decimal; JSON serializes it via FastAPI fine.

## KNOWN ISSUES
- POST /ingest unauthenticated — OK for local v1; needs shared token when
  scrapers run remote (Stage 2).
- No rate limit / payload cap on /ingest yet.
- /board is flat rows; grouping/sort for the wallboard is Phase D.
- Period codes q1–q4/ft only exercised; h1/h2 seeded but untested (Stage 3).

## NEXT VERTICAL SLICE
TB-002 — BetConstruct scraper (Phase C, plan tasks 10–15): Playwright service
that polls PokerBet live basketball, extracts game state + totals markets
(DOM map in betconstruct-sportsbook-scraping skill), normalizes to the
TB-001 contract, POSTs to /ingest. Slices: skeleton → event extraction →
market extraction → payload → poll loop (~20s, resilience).

## FIRST ACTION ON RESUME
cd ~/projects/odds-screen && docker compose ps && curl -s http://localhost:8002/health
