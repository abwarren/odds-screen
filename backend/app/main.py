"""Odds Screen API — FastAPI + asyncpg.

Phase A skeleton: /health + /board stub wired to the schema.
"""
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, HTTPException

from . import config, ingest, schemas


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=10)
    yield
    await app.state.pool.close()


app = FastAPI(title="Odds Screen API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    async with app.state.pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok"}


@app.post("/ingest", status_code=201)
async def ingest_tick(payload: schemas.IngestPayload):
    """Accept one normalized scrape tick; upsert + append-only dedupe."""
    try:
        return await ingest.apply(app.state.pool, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/board")
async def board():
    """Live events with current O/U selections (Phase D wallboard read model)."""
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT e.id            AS event_id,
                   e.external_ref,
                   e.home_team, e.away_team,
                   e.home_score, e.away_score,
                   e.period_code, e.clock_seconds,
                   p.code          AS period,
                   s.side, s.line_value,
                   v.odds
            FROM events e
            JOIN markets m     ON m.event_id = e.id
            JOIN periods p     ON p.id = m.period_id
            JOIN selections s  ON s.market_id = m.id
            JOIN v_current_odds v ON v.selection_id = s.id
            WHERE e.status = 'live'
              AND s.is_open = true
            ORDER BY e.id, p.ordinal, s.side
            """
        )
    return {"events": [dict(r) for r in rows]}
