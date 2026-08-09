"""Bet placement service — remote bets from the odds screen.

Lifecycle (enforced here):
    requested -> delivered -> confirmed | failed
    requested -> cancelled | failed | expired (stale, swept lazily)

The odds snapshot (odds_at_request) is taken from v_current_odds at request
time — the client never supplies odds. Idempotency via idempotency_key.
"""
from decimal import Decimal

from asyncpg import Pool

from . import config
from .schemas import BetIn, BridgeReportIn

_ALLOWED = {
    "delivered": {"requested"},
    "confirmed": {"delivered"},
    "failed": {"requested", "delivered"},
    "cancelled": {"requested"},
}

_COLUMNS = (
    "id, selection_id, bookmaker_id, side, line_value, odds_at_request, stake, "
    "status, mode, idempotency_key, requested_at, delivered_at, confirmed_at, failed_reason"
)
_B_COLUMNS = ", ".join(f"b.{c}" for c in _COLUMNS.split(", "))


async def place(pool: Pool, bet: BetIn) -> tuple[dict, bool]:
    """Create a bet request. Returns (bet_row, created); replay returns (row, False)."""
    stake = Decimal(str(bet.stake))
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO bets (selection_id, bookmaker_id, side, line_value,
                                  odds_at_request, stake, mode, idempotency_key)
                SELECT s.id, s.bookmaker_id, s.side, s.line_value, v.odds, $2, $3, $4
                FROM selections s
                JOIN v_current_odds v ON v.selection_id = s.id
                WHERE s.id = $1 AND s.is_open
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
                """,
                bet.selection_id, stake, bet.mode, bet.idempotency_key,
            )
            if row is None:
                existing = await conn.fetchrow(
                    "SELECT id FROM bets WHERE idempotency_key = $1", bet.idempotency_key
                )
                if existing:
                    return dict(await conn.fetchrow(
                        f"SELECT {_COLUMNS} FROM bets WHERE id = $1", existing["id"]
                    )), False
                raise ValueError("selection not found or not open")
            return dict(await conn.fetchrow(
                f"SELECT {_COLUMNS} FROM bets WHERE id = $1", row["id"]
            )), True


async def cancel(pool: Pool, bet_id: int) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE bets SET status = 'cancelled'
            WHERE id = $1 AND status = 'requested'
            RETURNING id, status
            """,
            bet_id,
        )
        if row is None:
            cur = await conn.fetchval("SELECT status FROM bets WHERE id = $1", bet_id)
            if cur is None:
                raise KeyError(bet_id)
            raise ValueError(f"bet {bet_id} is {cur}, not cancellable")
        return dict(row)


async def report(pool: Pool, rep: BridgeReportIn) -> dict:
    """Apply a bridge status transition. Raises KeyError / ValueError on bad state."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            cur = await conn.fetchval("SELECT status FROM bets WHERE id = $1", rep.bet_id)
            if cur is None:
                raise KeyError(rep.bet_id)
            if cur not in _ALLOWED[rep.status]:
                raise ValueError(f"invalid transition {cur} -> {rep.status}")
            return dict(await conn.fetchrow(
                """
                UPDATE bets SET status = $2,
                    delivered_at = CASE WHEN $2 = 'delivered' THEN now() ELSE delivered_at END,
                    confirmed_at = CASE WHEN $2 = 'confirmed' THEN now() ELSE confirmed_at END,
                    failed_reason = CASE WHEN $2 = 'failed' THEN $3 ELSE failed_reason END
                WHERE id = $1
                RETURNING id, status, delivered_at, confirmed_at, failed_reason
                """,
                rep.bet_id, rep.status, rep.reason,
            ))


async def commands(pool: Pool, bookmaker: str) -> list[dict]:
    """Pending bet commands for one bookmaker's bridge overlay (oldest first)."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE bets SET status = 'expired'
                WHERE status IN ('requested', 'delivered')
                  AND requested_at < now() - make_interval(mins => $1)
                """,
                config.BET_EXPIRY_MINUTES,
            )
            rows = await conn.fetch(
                """
                SELECT b.id AS bet_id, b.side, b.line_value, b.odds_at_request,
                       b.stake, b.mode,
                       e.external_ref, e.home_team, e.away_team,
                       p.code AS period, mt.code AS market_type
                FROM bets b
                JOIN selections s  ON s.id = b.selection_id
                JOIN markets m     ON m.id = s.market_id
                JOIN periods p     ON p.id = m.period_id
                JOIN market_types mt ON mt.id = m.market_type_id
                JOIN events e      ON e.id = m.event_id
                JOIN bookmakers bk ON bk.id = b.bookmaker_id
                WHERE b.status = 'requested' AND bk.code = $1
                ORDER BY b.id
                LIMIT 20
                """,
                bookmaker,
            )
            return [dict(r) for r in rows]


async def list_bets(pool: Pool, limit: int = 100) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_B_COLUMNS}, bk.name AS bookmaker
            FROM bets b
            JOIN bookmakers bk ON bk.id = b.bookmaker_id
            ORDER BY b.id DESC LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]
