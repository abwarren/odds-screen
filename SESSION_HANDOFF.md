# SESSION_HANDOFF — Odds Screen

## CURRENT OBJECTIVE
Build the odds screen (live SA bookmaker basketball totals wallboard + remote
bet placement) in vertical slices. TB-001 (ingest), TB-003 (bets), TB-004
(multi-book registry + cross-book comparison) complete. Next: TB-002 (real
BetConstruct scraper) to feed live data.

## LOCKED REQUIREMENTS
- v1: live basketball ONLY, Total Points O/U markets (q1–q4, ft).
- Stack: FastAPI + asyncpg + PostgreSQL 16 (Docker Compose, db:5434 / api:8002),
  vanilla JS/SVG wallboard (no Chart.js).
- Data source v1: PokerBet.co.za (BetConstruct) DOM scraping, ~20s cadence.
- Remote bet placement IN SCOPE (user request supersedes original
  "never auto-place"): default = slip populate + manual confirm on the book;
  auto-confirm is an explicit opt-in with slip-odds verification.
- Generic schema — markets/books/sports are new ROWS, never schema changes.
- 15 SA books registered (Chrome 'Books' folder); creds in user's password
  manager, added manually. 4 folder entries are noise (search links/terms/league).

## SYSTEM STATE
- Compose stack RUNNING: postgres:16 (5434), api (8002). Both healthy.
- API v0.3.0: /health, / (→/bets-ui), /board (open selections + bookmaker),
  /ingest, /bets (+cancel), /bridge/commands, /bridge/report, /bets-ui,
  /books (15 books), /compare?period= (cross-book matrix + best odds).
- DB: bookmakers seeded (15), v_matched_events view live, bets table live.
- Demo comparison data present (Heat/Nuggets across pokerbet/hollywoodbets/
  betway, Knicks/Nets, Lakers/Celtics from tests) — visible on /bets-ui.
- Test venv: repo `.venv` (pytest, pytest-asyncio, httpx, asyncpg, playwright 1.61.0).
- Repo: github.com/abwarren/odds-screen, branch main, local == origin.

## COMPLETED SLICES
- TB-001: ingest path — contract, upserts, append-only dedupe (Decimal),
  line-move lifecycle, /board. QA 🟢.
- TB-003: remote bet placement — bets table + state machine, X-Bet-Token auth,
  /bets + /bridge, Tampermonkey overlay (bridge/), /bets-ui control page.
  QA 🟢 (conditions: BET_TOKEN dev default, overlay C2 until live PokerBet run).
- TB-004: multi-book registry (15 books) + v_matched_events + /compare + /books
  + compare matrix UI. QA 🟢 (conditions: team aliases, per-book scrapers).

## FILES CHANGED (TB-004)
- db/schema.sql — v_matched_events view + 15-book seed
- backend/app/compare.py — /compare + /books read models
- backend/app/main.py — routes
- web/bets.html — Compare matrix (period tabs, best-odds ★)
- tests/test_compare.py — 4 tests
- docs/tracer_bullets/TB-004/ — README + QA + evidence/
- skill: betconstruct-sportsbook-scraping/references/sa-bookmakers.md (15 books)

## TESTS & RESULTS
`.venv/bin/python -m pytest tests/ -v` → **20 passed in 9.62s** (4 ingest +
4 bets + 4 compare + 8 overlay harness). Live loopback, no mocks.

## CRITICAL DISCOVERIES
- Cross-book matching needs team-ALIAS resolution ("LA Lakers" vs "Lakers");
  v1 matches normalized team pairs only (documented follow-up).
- Best-odds = max decimal odds per side in v1, even across different lines;
  line-aware comparison / consensus lines are Stage 4.
- Only PokerBet is BetConstruct; 14 books are 'unknown' platform — each needs
  its own DOM map (per-book scraper slices).
- Chrome 'Books' folder has 19 entries, 15 real books (4 noise entries).

## KNOWN ISSUES
- BET_TOKEN dev default (`dev-token-change-me`) must change before real money.
- /ingest unauthenticated (fine local; needs token for remote scrapers).
- Overlay needs a logged-in PokerBet browser; dev uses @require file://
  (bundle for release).
- /compare best-odds ignores line differences (v1).
- Team aliases unimplemented — false negatives on differently-named teams.
- Test suite leaves demo events in the live DB (visible on the board).

## NEXT VERTICAL SLICE
TB-002 — BetConstruct scraper (Phase C, plan tasks 10–15): Playwright service
that polls PokerBet live basketball, extracts game state + totals markets
(DOM map in betconstruct-sportsbook-scraping skill), normalizes to the
TB-001 contract, POSTs to /ingest. Fills the pokerbet column with LIVE data.

## FIRST ACTION ON RESUME
cd ~/projects/odds-screen && docker compose ps && curl -s http://localhost:8002/health
