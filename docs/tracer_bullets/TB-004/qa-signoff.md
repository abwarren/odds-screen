# TB-004 QA Sign-Off — Multi-Book Registry + Cross-Book Comparison

**Date:** 2026-08-10 | **Reviewer:** Hermes (vertical-slicing + tracer-bullets skills)

## Architecture — 🟢 Approved

- Registry is pure INSERTs into the existing generic `bookmakers` table — no
  schema reshapes; new books = new rows (plan requirement).
- Matching as a view (`v_matched_events`) over existing tables: no event_links
  table needed yet; canonical `match_id` = smallest event id in the normalized
  team-pair group.
- Comparison is a read-side projection: `v_matched_events` → markets →
  selections → `v_current_odds` → bookmakers, one query, grouped in Python.
- Best-odds flags computed per side (max decimal odds); line-aware comparison
  deferred to Stage 4 with consensus lines.

## Implementation — 🟢 Approved

- 15 books seeded idempotently (ON CONFLICT DO UPDATE name/meta; platform_type
  preserved — ingest upserts can't clobber it).
- /compare validates nothing about period/market_type — unknown values return
  `[]` (empty, no error), consistent with the read-model philosophy.
- UI: matrix renders only books present in matches; period tabs re-query
  /compare; best cells green with ★.

## Verification — 🟢 Approved

- Live loopback: 20/20 tests pass against the real stack (4 new compare tests).
- Live /compare output captured (evidence/): Heat vs Nuggets grouped across
  pokerbet/hollywoodbets/betway with correct per-book lines and best flags.
- /books returns all 15 registered books.

## Production Readiness — 🟡 Approved with Conditions

- ✅ Endpoints read-only, no auth needed (public odds data).
- ⚠️ Condition: team-ALIAS matching ("LA Lakers" vs "Lakers") not implemented —
  false negatives until the alias table lands. Tracked in SESSION_HANDOFF.
- ⚠️ Condition: the other 14 books have no scrapers yet — the matrix is
  PokerBet + seeded demo data until per-book scraper slices land.
- ⚠️ Condition: cross-book best-odds ignores line differences (222.5 vs 223.5)
  — Stage 4 line-aware comparison.

## Overall: 🟢 APPROVED (with conditions)

TB-004's registry, matching, and comparison read model are validated with
evidence. The next slice is TB-002 (real BetConstruct scraper) to feed the
pokerbet column with live data.
