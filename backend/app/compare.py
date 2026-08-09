"""Cross-book comparison read model — the same market across books (TB-004).

Games are matched across bookmakers via v_matched_events (normalized team
pair + sport). For a chosen market (period × market type) this returns, per
matched game, every book's line + over/under odds, plus the best odds per
side. Best is max decimal odds among books (line-aware comparison /
consensus lines are Stage 4).
"""
from asyncpg import Pool


async def markets(pool: Pool) -> list[dict]:
    """Market types that actually have live data (for the UI market tabs)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT mt.code, mt.name
            FROM markets mk
            JOIN market_types mt ON mt.id = mk.market_type_id
            JOIN events e ON e.id = mk.event_id
            WHERE e.status = 'live'
            ORDER BY mt.code
            """
        )
        return [dict(r) for r in rows]


async def compare(pool: Pool, period: str = "ft", market_type: str = "total_points") -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH canon AS (
                -- one canonical event per (match, book): the most recently
                -- seen, so repeated ingests of the same game don't stack
                SELECT vm.match_id, e.bookmaker_id, e.id,
                       row_number() OVER (
                           PARTITION BY vm.match_id, e.bookmaker_id
                           ORDER BY e.last_seen_at DESC, e.id DESC
                       ) AS rn
                FROM v_matched_events vm
                JOIN events e ON e.id = vm.event_id
                WHERE e.status = 'live'
            )
            SELECT c.match_id,
                   ev.home_team, ev.away_team, ev.status,
                   bk.code AS book, bk.name AS book_name,
                   s.side, s.line_value, v.odds
            FROM canon c
            JOIN events ev       ON ev.id = c.id
            JOIN markets mk      ON mk.event_id = ev.id
            JOIN periods p       ON p.id = mk.period_id
            JOIN market_types mt ON mt.id = mk.market_type_id
            JOIN selections s    ON s.market_id = mk.id AND s.is_open
            JOIN v_current_odds v ON v.selection_id = s.id
            JOIN bookmakers bk   ON bk.id = ev.bookmaker_id
            WHERE p.code = $1 AND mt.code = $2 AND ev.status = 'live'
            ORDER BY c.match_id, bk.code, s.side
            """,
            period, market_type,
        )

    matches: dict[int, dict] = {}
    for r in rows:
        m = matches.setdefault(r["match_id"], {
            "match_id": r["match_id"],
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "status": r["status"],
            "books": {},
        })
        book = m["books"].setdefault(r["book"], {
            "book_name": r["book_name"],
            "home": None, "draw": None, "away": None, "over": None, "under": None,
        })
        book[r["side"]] = {
            "line": float(r["line_value"]) if r["line_value"] is not None else None,
            "odds": float(r["odds"]),
        }

    # best odds per SIDE present in this match (home/away/draw for moneylines,
    # over/under for totals) — max decimal odds among books
    SIDES = ("home", "draw", "away", "over", "under")
    for m in matches.values():
        present = {s for s in SIDES if any(book[s] for book in m["books"].values())}
        m["best"] = {}
        for side in present:
            code, odds = max(((code, book[side]) for code, book in m["books"].items() if book[side]),
                             key=lambda c: c[1]["odds"])
            m["best"][side] = {"book": code, "odds": odds["odds"], "line": odds["line"]}

    return sorted(matches.values(), key=lambda m: m["match_id"])


async def books(pool: Pool) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT code, name, platform_type FROM bookmakers ORDER BY name"
        )
        return [dict(r) for r in rows]
