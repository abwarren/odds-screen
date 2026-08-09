# Odds Screen — Implementation Plan v1

> **Date:** 2026-08-09
> **Status:** Plan only — no code yet (committed to GitHub before building, per workflow)
> **Research:** OddsJam deep-dive completed (3 parallel agents, Aug 2026) — see Research Context section below.

---

## End Goal

A realtime odds screen (wallboard) for South African bookmakers showing live
basketball **Total Points Over/Under** markets for **Q1, Q2, Q3, Q4 and Full
Game** — every line and odds update visible on screen within one scrape cycle
(~20s), with the full odds history stored for later line-movement, CLV and +EV
analysis.

**The test:** open the screen during a live basketball game → all 5 O/U markets
for that game are displayed with per-book lines and odds; when a book moves a
line or odds, the screen reflects it within 20s; `odds_history` contains an
append-only trace of every observed change.

## Stages

- **Stage 1 (this plan):** Single source (PokerBet / BetConstruct DOM), live
  basketball totals Q1–Q4 + Full Game, wallboard UI, append-only odds history.
  *Success: live games on screen, 5 O/U markets each, updating ≤20s, data in Postgres.*
- **Stage 2:** Multi-book — add more SA bookmakers, best-odds / line comparison
  across books on the same screen.
- **Stage 3:** More markets & sports — halves, team totals, moneyline, spread,
  props; soccer, tennis. No schema changes required (generic model).
- **Stage 4:** Analytics — line movement charts, no-vig consensus lines, +EV
  detection, CLV tracking. All derivable from `odds_history`.

## Constraints & Decisions (from user)

- **Scope now:** live basketball ONLY; totals O/U only (Q1, Q2, Q3, Q4, Full Game).
- **Scalability:** schema is market-generic — adding markets/books later means
  INSERTs, not schema changes.
- **Data source v1:** BetConstruct-based bookmaker (PokerBet.co.za) via DOM
  scraping — see `betconstruct-sportsbook-scraping` skill for the DOM map
  (quarter totals live under the "Quarters" tab, game totals under "Match").
- **Stack (house pattern):** FastAPI + asyncpg + PostgreSQL (Docker Compose,
  mapped ports), vanilla JS/SVG wallboard (no Chart.js), Polling ≥ BetConstruct
  refresh cadence (~20s).
- **Never auto-place bets.** Screen is read-only display.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────┐     ┌──────────────┐
│ BetConstruct    │     │ scraper service  │     │ ingest API   │     │ Postgres     │
│ sportsbook DOM  │────▶│ (Playwright,     │────▶│ FastAPI      │────▶│ schema.sql   │
│ (PokerBet)      │     │  polls ~20s)     │     │ POST /ingest │     │ (append-only │
└─────────────────┘     └──────────────────┘     └──────────────┘     │  history)    │
                                                                      └──────┬───────┘
┌─────────────────┐     ┌──────────────────┐     ┌──────────────┐            │
│ Wallboard UI    │◀────│ screen API       │◀────│ SELECT v_    │            │
│ (vanilla JS/SVG,│     │ FastAPI, GET     │     │ current_odds │            │
│  polls ~5s)     │     │ /board?status=live│    └──────────────┘            │
└─────────────────┘     └──────────────────┘
```

- **Scraper** (`scraper/`): Playwright, loads live basketball event view,
  extracts game state (teams, scores, clock, period) + totals markets
  (game totals, quarter totals). Normalizes to a JSON payload, POSTs to ingest API.
- **Ingest API** (`backend/`): upserts bookmakers/competitions/events/markets/
  selections; appends to `odds_history` ONLY when odds changed (dedupe).
- **Screen API** (`backend/`): serves the live board from `v_current_odds`
  joined with events/markets — one query per poll.
- **Wallboard** (`web/`): grid — rows = live games, columns = Q1/Q2/Q3/Q4/FT;
  each cell shows Over & Under line + odds; green/red flash on change; header
  shows teams, score, clock, period.

## Database Schema

Full DDL: `db/schema.sql` (committed with this plan). Summary:

| Table | Purpose | Scalability note |
|---|---|---|
| `bookmakers` | sources (v1: PokerBet) | add rows for more books |
| `sports` / `competitions` | basketball now | add rows for more sports |
| `events` | games, live state (score/clock/period) | per-book event identity |
| `periods` | q1–q4, h1/h2, ft | seeded, already includes halves |
| `market_types` | total_points now | moneyline/spread/props = new rows |
| `markets` | event × period × market type | unique constraint per game/period/market |
| `selections` | book × market × side × line | line move ⇒ new row (history preserved) |
| `odds_history` | append-only time series | partition by time when large |
| `v_current_odds` | latest odds per selection (view) | screen read model |

## Tracer Bullet (vertical slice)

```
SLICE: ONE LIVE BASKETBALL GAME → Q1–Q4 + FT TOTALS ON SCREEN

Layer 1 — Scraper        → scrape_game(game) returns normalized payload
Layer 2 — Ingest API     → POST /ingest upserts event + 5 markets + 10 selections
Layer 3 — Postgres       → rows in events/markets/selections/odds_history
Layer 4 — Screen API     → GET /board returns the game with 5 O/U markets
Layer 5 — Wallboard      → game row renders: teams, score, clock, 5 O/U cells
Layer 6 — History        → second scrape with a changed odds appends a row
```

**Acceptance (end-to-end):**
1. Scraper run 1 on a live game → 5 markets appear on the board.
2. Odds change at source → next scrape → board reflects it; `odds_history` has 2 rows for that selection.
3. Line moves 222.5 → 223.5 → new selection row, old history intact.
4. Game ends → status `ended`, markets `settled`, row stays visible with final score.
5. Restart everything → board repopulates from DB (no data loss).

## Tasks (Stage 1 — bite-sized)

### Phase A — Foundation (repo, stack, DB)

1. **Commit plan + schema** — this file + `db/schema.sql` + README → push to GitHub. *(done with this commit)*
2. **Docker Compose** — `docker-compose.yml`: postgres:16 (mapped port), api, scraper services; healthchecks.
3. **DB init** — mount `db/schema.sql` as init script; verify `psql \dt` shows all tables + seeded periods/market_types.
4. **Backend skeleton** — FastAPI app, `/health`, asyncpg pool, settings via env.

### Phase B — Ingest path

5. **Ingest contract** — Pydantic models matching the normalized payload (event, market[], selection[], odds[]).
6. **Upsert logic** — bookmaker/competition/event upsert; `INSERT ... ON CONFLICT DO UPDATE`.
7. **Market + selection sync** — ensure market rows for the 5 periods; open/close selections on line changes.
8. **Odds append (dedupe)** — append to `odds_history` only if odds differ from latest; else update `events.last_seen_at`.
9. **Ingest test** — curl a sample live-game payload → verify all rows + view.

### Phase C — Scraper

10. **Scraper skeleton** — Playwright launch, login-less live basketball listing.
11. **Game extraction** — teams, scores, clock, period from event rows (per skill DOM map).
12. **Market extraction** — game totals ("Match" tab) + quarter totals ("Quarters" tab).
13. **Normalized payload** — map DOM → ingest contract; handle missing/settled quarters.
14. **Poll loop** — ~20s cadence, resilience (re-login, reconnect, backoff), logs.
15. **Live test** — run against a real live game; verify board updates.

### Phase D — Screen API + Wallboard

16. **Board endpoint** — `GET /board`: live events + `v_current_odds` join, one query.
17. **Wallboard shell** — game rows × 5 O/U columns; header (teams, score, clock, period).
18. **Realtime update** — 5s poll of `/board`; diff previous state; green/red flash on change.
19. **Visual polish** — dark wallboard theme, best-odds highlight within a book, settled/ended state styling.
20. **End-to-end verification** — full tracer-bullet acceptance run; then commit.

## Research Context — What an OddsJam-Style Odds Screen Looks Like

Deep dive (3 parallel research agents, cited sources) into OddsJam — the reference
for what an "odds screen" product entails. Key takeaways for this build:

**The company.** OddsJam (Odds Holdings) founded by Ankit Goyal & Alex Monahan,
launched April 2021; bootstrapped and profitable, acquired by Gambling.com Group
(now Grandstand) for up to $160M (closed Jan 2025); ~$26M revenue / ~$12M EBITDA
in 2024. CEO Matt Restivo (ex-Action Network). ~30-40 staff. Business = vertical
integration: free odds pages (SEO + affiliate deep-links to books) → paid consumer
tools (OddsJam Pro) → enterprise API (OpticOdds) + "OddsJam Screen" (B2B odds board).

**The screen product.** OddsJam Screen (their B2B odds board, sold to syndicates/
traders/books) is a realtime grid of markets across 100+ books with custom weighted
consensus lines, notifications on line moves / market posting / injuries /
settlements / time changes, and Slack + Teams integration. The consumer site is
the same data reframed as +EV screener, arbitrage, middles, promo converter,
parlay builder, bet tracker with CLV. Our v1 wallboard is the SA-market seed of
this: one book, live totals — but the same grid + movement-flash + alert shape.

**Data & math (the playbook).**
- Ingestion is polling/scraping of books' public endpoints, per-book freshness
  tracked via `last-polled` timestamps; they claim 1M+ odds/sec across "hundreds
  of servers" and 100-150+ books. Our ~20s poll of one BetConstruct book is the
  same pattern at v1 scale — per-book `last_polled` freshness belongs in Stage 2.
- Normalization: decimal odds in API, American in US UI; we stay decimal (SA).
- History: opening odds → live line changes → closing lines all stored; "beating
  the closing line" (CLV) is their core metric. Our append-only `odds_history`
  is exactly this shape — Stage 4 consumes it.
- Fair odds: devigged consensus "Perfect Line" across books, user-selectable
  devig methods (Multiplicative / Additive / Power (default) / Worst / Best case);
  EV = (win prob × profit) − (loss prob × stake); Kelly staking. Stage 4 targets.

**Market context.** Post-PASPA US handle exploded (→ $100B+/yr); data flows via
(a) official league feeds (Sportradar/Genius), (b) books' own unofficial JSON
endpoints, (c) scrapers aggregating those — OddsJam's model, (d) exchange APIs.
Competitors: The Odds API / SportsDataIO (dev-friendly data APIs), Unabated /
BetStamp / Pikkit (consumer edge tools). **The SA angle: no OddsJam equivalent
exists for SA bookmakers — the odds-comparison/+EV gap is open, and BetConstruct
books have no public API, so DOM scraping is the only route (same as OddsJam's
origins; Sportradar itself started by scraping book odds).**

**Risk note.** Swish Analytics sued OddsJam/OpticOdds for data misappropriation
(~$100M claim, Dec 2024; motion to dismiss rejected). Scraping books carries
ToS/IP exposure everywhere, SA included. Mitigation for this build: read-only,
rate-limited, public-page scraping; no account automation; no bet placement; and
never claim data provenance we don't have. (This is a display/analytics tool, not
a resale business — keeps the risk profile low.)

## Open Questions

1. **Which bookmakers beyond PokerBet?** RESOLVED — 15 SA books bookmarked in Chrome
   folder "Books" (extracted 2026-08-09): Easybet, Sportingbet, PokerBet, World Sports
   Betting, Goldrush (bet.co.za), Sunbet, Hollywoodbets, Betway SA (new.betway.co.za),
   Gbets, 10Bet, Playa Bets, Lulabet, YesPlay, Bettabets, Supabets. All are Stage 2
   targets (per-book scrapers). Credentials live in the user's password manager —
   the user adds them manually on this machine, never via the agent.
2. **Scraper hosting** — same Docker Compose as the API, or a separate box/service (cf. blm-scraper.service pattern)?
3. **Wallboard layout** — single screen grid of ALL live games, or per-game drill-down? (Default: grid of live games, click → game detail.)
4. **Historical depth** — keep every odds change forever, or start pruning pre-rollout data once volume grows?
