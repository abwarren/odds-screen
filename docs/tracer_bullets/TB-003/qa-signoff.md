# TB-003 QA Sign-Off — Remote Bet Placement from the Odds Screen

**Date:** 2026-08-10 | **Reviewer:** Hermes (vertical-slicing + tracer-bullets skills)

## Architecture — 🟢 Approved

- `bets` table lifecycle (`requested → delivered → confirmed | failed`,
  `requested → cancelled | failed | expired`) matches the plan's "screen →
  book" direction; stale bets are swept lazily on the next bridge poll
  (`BET_EXPIRY_MINUTES=15`) — no cron, eventually consistent by design.
- Odds are snapshotted server-side from `v_current_odds` at request time — the
  client never supplies the price, so a stale screen can't place at a phantom
  line.
- Idempotency key is the dedupe: replay returns the original bet (200), no
  double placement.
- Explicit transition map (`_ALLOWED`) — illegal transitions are 409s, never
  silent state corruption.
- Money routes are default-closed: `X-Bet-Token` required, unset `BET_TOKEN`
  ⇒ 503. No credentials stored anywhere in the stack.
- `/board` now carries `selection_id` — the UI ↔ bridge ↔ API handoff key.

## Implementation — 🟢 Approved

- `BetIn` validated at the boundary: stake 0–100 000, `mode` manual|auto,
  `idempotency_key` ≥ 8 chars; `BridgeReportIn` restricts status to
  delivered|confirmed|failed + optional reason.
- `commands()` expires stale bets first, then returns pending commands for ONE
  bookmaker, oldest first — the bridge polls per book with no double-delivery.
- Overlay core is pure DOM (no framework): event row → Match/Quarters tab →
  Total Points / {N}th Quarter section → line+side button → slip fill, with
  waitForSlipLeg / slipShows / slipShowsOdds guards.
- Manual mode reports `delivered`, waits for the human to click Place Bet on
  PokerBet, then `confirmed`. Auto mode re-verifies slip odds against
  `odds_at_request` and aborts with `failed` if they moved — the safety check
  lives in the same code path that clicks.
- Control page (`web/bets.html`) is a minimal dark page: live board, stake
  input + Place, bets table with cancel, token in localStorage, 5s poll.

## Verification — 🟢 Approved

- Full suite green: **16 passed** (4 ingest regression + 4 bets + 8 overlay
  harness) against the real running stack — no mocks
  (evidence/test-results.log).
- Bets tests cover: 401s without token; manual flow end-to-end incl. idempotent
  replay and command visibility; cancel + invalid transitions (409) + failed
  reason; validation 422s, closed-selection rejection, expiry.
- Overlay harness (8 Playwright tests) drives a fixture page replicating the
  BetConstruct DOM: odds-button finding, stake set, manual delivered→confirmed
  via toast, auto clicks place + confirms, auto aborts on moved odds,
  event-not-found fails cleanly.

## Production Readiness — 🟡 Approved with Conditions

- ✅ Full lifecycle works end-to-end against the live stack; deployable via
  existing docker-compose.
- ⚠️ Condition: `BET_TOKEN` dev default (`dev-token-change-me`) MUST change
  before any real money — documented, not yet enforced.
- ⚠️ Condition: overlay core is C2 (harness-verified against a fixture DOM),
  NOT C3 until run against the real logged-in PokerBet page.
- ⚠️ Condition: the bridge is browser-side — a browser must be logged into
  PokerBet.co.za on the machine for placement to work; manual mode still
  requires the human to click Place Bet.

## Overall: 🟢 APPROVED (with conditions)

TB-003's architecture and implementation are validated with evidence, subject
to the three production conditions above (real BET_TOKEN, real-session overlay
run, logged-in browser). TB-002 (BetConstruct scraper) may proceed.
