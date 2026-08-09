# TB-003 — Remote Bet Placement from the Odds Screen

**Status:** ✅ PASSED (bets API C3; overlay core C2 — harness-verified; live
PokerBet placement C0 — needs the real logged-in browser)
**Date:** 2026-08-10
**Repo:** github.com/abwarren/odds-screen

## What Was Demonstrated

The third vertical slice: **placing a bet on PokerBet from the odds screen** —
bets placed via the API are delivered into the user's OWN logged-in PokerBet
session by a browser-side bridge (userscript), with the full lifecycle tracked
in Postgres. This is the tracer bullet for the "screen → book" direction: it
proves the bet contract, the lifecycle state machine, and the DOM overlay can
carry a stake from the screen to a real bookmaker slip and report the outcome
back.

| Layer | What it proves |
|---|---|
| Bet API | `POST /bets` — server-side odds snapshot (client never supplies odds), idempotent via `idempotency_key` |
| Lifecycle | `requested → delivered → confirmed \| failed`; `requested → cancelled \| failed \| expired` (15 min sweep) |
| Bridge commands | `GET /bridge/commands?bookmaker=` — pending commands for one book, oldest first |
| Overlay core | pure-DOM `window.OddsScreenBridge` — finds event/market/odds button, fills slip, reports status |
| Control page | `GET /bets-ui` (web/bets.html) — live board + stake input + bets table with cancel |

## The Two Modes

- **Manual (default):** the bridge fills the PokerBet slip with the line and
  stake, reports `delivered`, then WAITS — the user clicks **Place Bet** on
  PokerBet themselves; the bridge then reports `confirmed`.
- **Auto (explicit opt-in, `mode: auto`):** after `delivered` the bridge
  re-reads the slip odds and aborts (`failed`, "odds moved since request") if
  they no longer match `odds_at_request`, then clicks Place Bet itself and
  confirms on the toast.

## Safety Properties

- No credentials in this stack — bets land in the user's own logged-in PokerBet
  session; the bridge never logs in.
- Client never supplies odds — the price is snapshotted from `v_current_odds`
  at request time, so a stale screen can't place at a phantom line.
- Idempotent placement — retrying the same `idempotency_key` returns the
  original bet (200), never a double.
- Strict state machine — every illegal transition is a 409, never silent.
- Default-closed API — all money routes require `X-Bet-Token`; unset
  `BET_TOKEN` ⇒ 503.
- Auto mode is opt-in and re-verifies slip odds before clicking Place Bet.

## Automated Tests (evidence/test-results.log)

```
16 passed
```

- `tests/test_ingest.py` — 4 (TB-001 regression, live loopback).
- `tests/test_bets.py` — 4: auth 401s; manual flow incl. idempotent replay +
  command visibility + delivered→confirmed; cancel + invalid transitions 409 +
  failed reason; validation 422s + closed selection + expiry.
- `tests/test_overlay_harness.py` — 8 Playwright tests against a fixture page
  replicating the BetConstruct DOM: odds-button finding, stake set, manual
  delivered→confirmed via toast, auto mode clicks place + confirms, auto aborts
  on moved odds, event-not-found fails cleanly.

## Capability Levels

| Capability | Level |
|---|---|
| Bets API (place / cancel / report / commands) | C3 (QA verified) |
| Idempotent placement + server-side odds snapshot | C3 (QA verified) |
| Bet lifecycle state machine + expiry sweep | C3 (QA verified) |
| Overlay bridge core (DOM ops, slip fill, both modes) | C2 (Playwright harness, fixture DOM) |
| Live placement on PokerBet.co.za (real logged-in browser) | C0 (needs the real session — browser-side) |
| Wallboard bet UI (Phase D embed) | C0 (designed) |

## Critical Discoveries

- **Idempotency-key replay.** Same key ⇒ 200 + original bet (201 on first
  create). The key IS the dedupe — protects double-clicks and bridge retries
  without a unique constraint on the whole request.
- **Odds must be snapshotted server-side.** Client-supplied odds would let a
  stale screen place at a price that no longer exists. Snapshotting from
  `v_current_odds` at request time makes the API the source of truth.
- **Explicit transition map.** `_ALLOWED` in `backend/app/bets.py` — every
  illegal transition (e.g. `cancelled → confirmed`) is a 409, not silent state.
- **Playwright harness pitfalls.** A `page.evaluate` parameter named
  `arguments`/`args` collides with the injected wrapper's arguments — name
  parameters explicitly. Functions passed through `expose_function` must be
  plain serializable closures; anything capturing live state silently breaks.
  (Both bitten us in `tests/test_overlay_harness.py`.)

## Files

```
db/schema.sql                                  MOD  — bets table (applied live)
backend/app/schemas.py                         MOD  — BetIn, BridgeReportIn
backend/app/bets.py                            NEW  — place/cancel/report/commands/list_bets
backend/app/main.py                            MOD  — /bets*, /bridge/*, /bets-ui; X-Bet-Token guard
web/bets.html                                  NEW  — dark control page (board + stake + bets table)
bridge/overlay-core.js                         NEW  — pure-DOM bridge core (OddsScreenBridge)
bridge/tampermonkey/odds-screen-bet-bridge.user.js  NEW — pokerbet.co.za userscript
docker-compose.yml                             MOD  — repo-root build context; BET_TOKEN, BET_EXPIRY_MINUTES
tests/test_bets.py                             NEW  — 4 API tests (live loopback)
tests/test_overlay_harness.py                  NEW  — 8 Playwright overlay tests (fixture DOM)
scripts/demo_tb003.py                          NEW  — reproducible demo walkthrough
docs/tracer_bullets/TB-003/                    NEW  — this doc + evidence/
```

## Next Vertical Slice

**TB-002 — real BetConstruct scraper (Phase C).** Playwright service polling
PokerBet live basketball, extracting game state + totals markets into the
TB-001 ingest contract, POSTing to `/ingest`. After that, wallboard **Phase D**
embeds the bet control UI (`bets.html`) into the screen.
