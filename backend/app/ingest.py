"""Ingest service — upsert + append-only dedupe against the odds schema.

Rules enforced here (from the plan):
  * bookmaker / sport / competition / event are upserted by natural key.
  * A market is one row per (event, period, market_type) — upserted.
  * A selection is one row per (market, bookmaker, side, line_value).
    A LINE MOVE (e.g. 222.5 -> 223.5) closes the old row (is_open=false)
    and inserts a new one — old history stays intact.
  * odds_history is APPEND-ONLY: a row is inserted only when the odds differ
    from the latest captured value for that selection (dedupe). Identical
    ticks update nothing except events.last_seen_at.
"""
from decimal import Decimal

from asyncpg import Pool, Record

from .schemas import IngestPayload


def _dec(value: float | None) -> Decimal | None:
    """Normalize a float to Decimal for exact DB comparisons.

    numeric(6,2) comes back from asyncpg as Decimal; comparing it to a float
    is exact-value comparison (Decimal('1.90') != 1.9 is True), which would
    defeat odds dedupe. Decimal-vs-Decimal equality ignores scale.
    """
    return None if value is None else Decimal(str(value))


async def apply(pool: Pool, payload: IngestPayload) -> dict:
    """Apply one normalized scrape tick. All-or-nothing via transaction."""
    stats = {
        "markets": 0,
        "selections": 0,
        "odds_appended": 0,
        "lines_moved": 0,
        "unchanged": 0,
    }
    async with pool.acquire() as conn:
        async with conn.transaction():
            bookmaker_id = await conn.fetchval(
                """
                INSERT INTO bookmakers (code, name, platform_type)
                VALUES ($1, $1, 'betconstruct')
                ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                payload.bookmaker,
            )

            sport_id = await conn.fetchval(
                """
                INSERT INTO sports (code, name)
                VALUES ($1, $1)
                ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                payload.event.sport,
            )

            competition_id = await conn.fetchval(
                """
                INSERT INTO competitions (sport_id, name, external_ref)
                VALUES ($1, $2, $3)
                ON CONFLICT (sport_id, name)
                DO UPDATE SET external_ref = EXCLUDED.external_ref
                RETURNING id
                """,
                sport_id,
                payload.event.competition,
                payload.event.external_ref,
            )

            event_id = await conn.fetchval(
                """
                INSERT INTO events (competition_id, bookmaker_id, external_ref,
                                    home_team, away_team, starts_at, status,
                                    period_code, clock_seconds, home_score, away_score)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (bookmaker_id, external_ref) DO UPDATE SET
                    home_team     = EXCLUDED.home_team,
                    away_team     = EXCLUDED.away_team,
                    starts_at     = EXCLUDED.starts_at,
                    status        = EXCLUDED.status,
                    period_code   = EXCLUDED.period_code,
                    clock_seconds = EXCLUDED.clock_seconds,
                    home_score    = EXCLUDED.home_score,
                    away_score    = EXCLUDED.away_score,
                    last_seen_at  = now()
                RETURNING id
                """,
                competition_id,
                bookmaker_id,
                payload.event.external_ref,
                payload.event.home_team,
                payload.event.away_team,
                payload.event.starts_at,
                payload.event.status,
                payload.event.period_code,
                payload.event.clock_seconds,
                payload.event.home_score,
                payload.event.away_score,
            )

            for market in payload.markets:
                period_id = await conn.fetchval(
                    "SELECT id FROM periods WHERE code = $1", market.period
                )
                if period_id is None:
                    raise ValueError(f"unknown period code: {market.period!r}")
                market_type_id = await conn.fetchval(
                    "SELECT id FROM market_types WHERE code = $1", market.market_type
                )
                if market_type_id is None:
                    raise ValueError(f"unknown market type: {market.market_type!r}")

                market_id = await conn.fetchval(
                    """
                    INSERT INTO markets (event_id, period_id, market_type_id, status)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (event_id, period_id, market_type_id)
                    DO UPDATE SET status = EXCLUDED.status
                    RETURNING id
                    """,
                    event_id,
                    period_id,
                    market_type_id,
                    market.status,
                )
                stats["markets"] += 1

                for sel in market.selections:
                    stats["selections"] += await _sync_selection(
                        conn, market_id, bookmaker_id, sel, stats
                    )

    return {"event_id": event_id, **stats}


async def _sync_selection(conn, market_id: int, bookmaker_id: int, sel, stats: dict) -> int:
    """Sync one selection. Returns 1 if a NEW selection row was created, else 0.

    Appends to odds_history only on an odds change (dedupe). Closes the old
    open selection when the line moves.
    """
    cur: Record | None = await conn.fetchrow(
        """
        SELECT id, line_value
        FROM selections
        WHERE market_id = $1 AND bookmaker_id = $2 AND side = $3 AND is_open
        ORDER BY id DESC
        LIMIT 1
        """,
        market_id,
        bookmaker_id,
        sel.side,
    )
    sel_line = _dec(sel.line_value)

    if cur is not None and cur["line_value"] == sel_line:
        selection_id = cur["id"]  # same line still open — reuse
        created = 0
    else:
        if cur is not None:
            # line moved — close the old selection, keep its history intact
            await conn.execute("UPDATE selections SET is_open = false WHERE id = $1", cur["id"])
            stats["lines_moved"] += 1
        selection_id = await conn.fetchval(
            """
            INSERT INTO selections (market_id, bookmaker_id, side, line_value)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (market_id, bookmaker_id, side, line_value)
            DO UPDATE SET is_open = true
            RETURNING id
            """,
            market_id,
            bookmaker_id,
            sel.side,
            sel_line,
        )
        created = 1

    latest_odds = await conn.fetchval(
        """
        SELECT odds FROM odds_history
        WHERE selection_id = $1
        ORDER BY captured_at DESC, id DESC
        LIMIT 1
        """,
        selection_id,
    )
    sel_odds = Decimal(str(sel.odds))  # odds is a required float — never None

    if latest_odds is None or latest_odds != sel_odds:
        await conn.execute(
            """
            INSERT INTO odds_history (selection_id, odds, implied_prob, source)
            VALUES ($1, $2, $3, $4)
            """,
            selection_id,
            sel_odds,
            round(Decimal(1) / sel_odds, 4),
            sel.source,
        )
        stats["odds_appended"] += 1
    else:
        stats["unchanged"] += 1

    return created
