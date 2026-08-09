"""Cross-book comparison read model — the same market across books (TB-004).

Games are matched across bookmakers via v_matched_events (normalized team
pair + sport). For a chosen market (period × market type) this returns, per
matched game, every book's line + over/under odds, plus the best odds per
side. Best is max decimal odds among books (line-aware comparison /
consensus lines are Stage 4).
"""
from asyncpg import Pool


async def compare(pool: Pool, period: str = "ft", market_type: str = "total_points") -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT vm.match_id,
                   ev.home_team, ev.away_team, ev.status,
                   bk.code AS book, bk.name AS book_name,
                   s.side, s.line_value, v.odds
            FROM v_matched_events vm
            JOIN events ev       ON ev.id = vm.event_id
            JOIN markets mk      ON mk.event_id = ev.id
            JOIN periods p       ON p.id = mk.period_id
            JOIN market_types mt ON mt.id = mk.market_type_id
            JOIN selections s    ON s.market_id = mk.id AND s.is_open
            JOIN v_current_odds v ON v.selection_id = s.id
            JOIN bookmakers bk   ON bk.id = ev.bookmaker_id
            WHERE p.code = $1 AND mt.code = $2 AND ev.status = 'live'
            ORDER BY vm.match_id, bk.code, s.side
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
            "book_name": r["book_name"], "over": None, "under": None,
        })
        book[r["side"]] = {
            "line": float(r["line_value"]) if r["line_value"] is not None else None,
            "odds": float(r["odds"]),
        }

    for m in matches.values():
        best = {}
        for side in ("over", "under"):
            cands = [(code, b[side]) for code, b in m["books"].items() if b[side]]
            if cands:
                code, odds = max(cands, key=lambda c: c[1]["odds"])
                best[side] = {"book": code, "odds": odds["odds"], "line": odds["line"]}
            else:
                best[side] = None
        m["best"] = best

    return sorted(matches.values(), key=lambda m: m["match_id"])


async def books(pool: Pool) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT code, name, platform_type FROM bookmakers ORDER BY name"
        )
        return [dict(r) for r in rows]
