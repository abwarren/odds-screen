# Odds Screen

Realtime odds screen for South African bookmakers — live basketball Total
Points Over/Under wallboard (Q1–Q4 + Full Game), with append-only odds history
for later line-movement / CLV / +EV analysis, and remote bet placement from
the screen into your own logged-in PokerBet session.

**Status:** TB-001 (ingest) + TB-003 (remote bet placement) + TB-004 (multi-book
comparison) complete and QA-approved. Next: TB-002 BetConstruct scraper (Phase C).

- Plan: `docs/plans/2026-08-09-odds-screen-v1.md`
- Schema: `db/schema.sql`
- Tracer bullet evidence: `docs/tracer_bullets/TB-001/`, `docs/tracer_bullets/TB-003/`, `docs/tracer_bullets/TB-004/`
- Handoff: `SESSION_HANDOFF.md`

Stack (house pattern): FastAPI + asyncpg + PostgreSQL (Docker Compose, mapped
ports) + vanilla JS wallboard. Data source v1: BetConstruct-based bookmaker
(PokerBet.co.za) via DOM scraping. 15 SA books registered (Chrome 'Books' folder).

## Run it

```bash
docker compose up -d --build          # db:5434, api:8002
curl localhost:8002/health            # {"status":"ok"}
.venv/bin/python -m pytest tests/ -v  # live-loopback acceptance suite
.venv/bin/python scripts/demo_tb001.py  # ingest lifecycle demo
.venv/bin/python scripts/demo_tb003.py  # bet placement demo
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness (SELECT 1) |
| `GET /board` | live events × open O/U selections (one query; includes selection_id, bookmaker) |
| `GET /compare?period=ft` | same market across books: per matched game, per book line + odds, best per side |
| `GET /books` | registered bookmakers (15) |
| `POST /ingest` | normalized scrape tick → upserts + append-only history |
| `POST /bets` | place a bet — server-side odds snapshot, idempotent via idempotency_key |
| `GET /bets` | list bets |
| `POST /bets/{id}/cancel` | cancel a `requested` bet |
| `GET /bridge/commands?bookmaker=` | pending bridge commands for one book (oldest first) |
| `POST /bridge/report` | bridge status report (delivered / confirmed / failed) |
| `GET /bets-ui` | bet control page (web/bets.html) |

Ingest payload contract: `backend/app/schemas.py` — bookmaker code, event
(identity + live state), markets (period × market_type) with over/under
selections (line_value, decimal odds). Line moves close the old selection row
and start a new one; identical odds ticks append nothing.

## Remote bet placement

Bets placed via the API are delivered into **your own logged-in PokerBet
session** by a browser-side bridge — no credentials ever touch this stack.

- **Manual mode (default):** the bridge fills the PokerBet slip with the line
  and stake, then YOU click Place Bet on PokerBet; the bridge reports the
  result back.
- **Auto mode (explicit opt-in):** the bridge verifies the slip odds still
  match the odds at request time, clicks Place Bet itself, and confirms on the
  toast. If the odds moved, the bet fails with "odds moved since request".

All bet routes require an `X-Bet-Token` header (env `BET_TOKEN`; the dev
default `dev-token-change-me` MUST be changed before real money; no token
configured ⇒ 503).

### One-time bridge install

1. Tampermonkey → "Create a new script" → replace the contents with
   `bridge/tampermonkey/odds-screen-bet-bridge.user.js` (or import it via
   Utilities → "Import from file").
2. Enable **"Allow access to file URLs"** for the userscript (it loads
   `bridge/overlay-core.js` from a file path in dev; bundle for release).
3. Log into pokerbet.co.za in that browser and open a live basketball event —
   the script polls `http://localhost:8002/bridge/commands` every ~2s, shows a
   status chip, and prompts for the token on first run (cached afterwards).

## Cross-book comparison

Games are matched across books by normalized team pair + sport
(`v_matched_events` view). `GET /compare?period=ft` returns, per matched game,
each book's line + over/under odds, with the best odds per side flagged
(green ★ in the UI matrix on `/bets-ui`, Q1–Q4/FT tabs). Team-ALIAS matching
("LA Lakers" vs "Lakers") and line-aware best-odds are documented follow-ups.
The other 14 books need per-book scrapers to fill their matrix columns with
live data (only PokerBet is BetConstruct so far).
