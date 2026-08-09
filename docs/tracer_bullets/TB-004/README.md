# TB-004 — Multi-Book Registry + Cross-Book Comparison

**Status:** ✅ PASSED (registry C3, comparison C2 — demonstrated, tests green)
**Date:** 2026-08-10
**Repo:** github.com/abwarren/odds-screen

## What Was Demonstrated

Stage 2 seed of the odds screen: all **15 real SA bookmakers** from the user's
Chrome "Books" folder registered, and the **same market compared across books**
— per matched game, per book: line + over/under odds, with the best odds per
side flagged.

The Chrome folder has **19 entries**; 4 are noise (2 Google-search links for
hollywoodbets/betway, an easybet terms page, the sa20.co.za league site) —
all already covered by real book entries, so 15 books were registered.

| Layer | What it proves |
|---|---|
| Registry | `bookmakers` seeded with all 15 books (code/name/platform/meta.domain) |
| Matching | `v_matched_events` view groups the same game across books (normalized team pair + sport → canonical `match_id`) |
| Compare API | `GET /compare?period=ft` → per match, per book: line + O/U odds; `best` flags per side |
| Books API | `GET /books` → registry (powers the matrix header) |
| UI | Compare matrix: rows = games, columns = books, cells = "over line @ odds / under line @ odds", best odds green ★; Q1–Q4/FT period tabs |

## Live Demo (evidence/)

```
/compare?period=ft — 3 matches
Heat vs Nuggets (match 31)
         betway: over 223.5 @ 1.9  under 223.5 @ 1.7
  hollywoodbets: over 222.5 @ 1.8  under 222.5 @ 1.85
       pokerbet: over 222.5 @ 1.85  under 222.5 @ 1.9
  BEST: over -> betway 1.9 | under -> pokerbet 1.9
```

## Automated Tests (20 passed total; 4 new)

- `test_books_registry` — all 15 Chrome-folder books present; pokerbet is betconstruct.
- `test_compare_groups_same_game_across_books` — 3 books' events for one game
  group into a single match; lines/odds per book correct; best flags correct.
- `test_compare_period_filter_and_unmatched` — period=q1 shows only books with
  q1 data; an unrelated game stays its own match.
- `test_compare_empty` — unknown market type → `[]`, no error.

## Capability Levels

| Capability | Level |
|---|---|
| Bookmaker registry (15 books) | C3 (QA verified) |
| Cross-book event matching | C2 (demonstrated) |
| /compare read model + best odds | C2 (demonstrated) |
| Compare matrix UI | C2 (demonstrated) |
| Live multi-book DATA (scrapers for 14 books) | C0 (designed — per-book scraper slices) |

## Critical Discoveries

- **Team-name matching is the hard part of line shopping.** The view matches
  normalized team pairs ("Heat"/"Nuggets" exact). Books use aliases ("LA
  Lakers" vs "Lakers", "76ers" vs "Philadelphia 76ers") — a team-alias table
  is the documented follow-up. Same for competition names.
- **Best odds is max-odds-per-side** in v1, even across different lines
  (222.5 vs 223.5). Line-aware comparison / consensus lines are Stage 4.
- **Only PokerBet has a confirmed platform (BetConstruct).** The other 14
  books are `platform_type='unknown'` — each needs its own DOM map/scraper.

## Files

```
db/schema.sql                    MOD — v_matched_events view + 15-book seed
backend/app/compare.py           NEW — /compare + /books read models
backend/app/main.py              MOD — /compare, /books routes
web/bets.html                    MOD — Compare matrix section (period tabs)
tests/test_compare.py            NEW — 4 live-loopback tests
docs/tracer_bullets/TB-004/      NEW — this doc + QA + evidence/
```

## Next Vertical Slice

**TB-002 — the real BetConstruct scraper (Phase C)**: polls PokerBet live
basketball, normalizes to the ingest contract, POSTs to /ingest. That fills
the pokerbet column of the matrix with LIVE data. Then per-book scrapers for
the other 14 books (each its own slice, platform-specific DOM maps) fill the
rest — the comparison screen needs ≥2 books live to be useful.
