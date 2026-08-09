"""Odds Screen API — FastAPI + asyncpg.

TB-001: /health, POST /ingest (upserts + append-only history), /board.
TB-003: remote bet placement — /bets, /bridge (Tampermonkey overlay), /bets-ui.
"""
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from . import bets, compare, config, ingest, realtime, schemas


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=10)
    yield
    await app.state.pool.close()


app = FastAPI(title="Odds Screen API", version="0.3.0", lifespan=lifespan)

_BETS_HTML = (Path(__file__).resolve().parent.parent / "web" / "bets.html").read_text()


def require_bet_token(x_bet_token: str | None = Header(default=None)):
    """Auth for money endpoints. Default-closed: unset BET_TOKEN => 503."""
    if not config.BET_TOKEN:
        raise HTTPException(status_code=503, detail="betting not configured (set BET_TOKEN)")
    if x_bet_token != config.BET_TOKEN:
        raise HTTPException(status_code=401, detail="invalid or missing X-Bet-Token")


# --------------------------------------------------------------------------- #
# Read side
# --------------------------------------------------------------------------- #

@app.get("/", include_in_schema=False)
async def root():
    """Landing: send browsers to the control page (wallboard lands here in Phase D)."""
    return RedirectResponse("/bets-ui", status_code=307)


@app.get("/health")
async def health():
    async with app.state.pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok"}


@app.get("/board")
async def board():
    """Live events with current O/U selections (Phase D wallboard read model).

    One game per row GROUP: events are deduped by match (v_matched_events) —
    the canonical event per match is the most recently updated one, so test
    re-ingests of the same game collapse into a single board entry.
    """
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH canon AS (
                SELECT vm.match_id,
                       e.id,
                       row_number() OVER (
                           PARTITION BY vm.match_id
                           ORDER BY e.last_seen_at DESC, e.id DESC
                       ) AS rn
                FROM v_matched_events vm
                JOIN events e ON e.id = vm.event_id
                WHERE e.status = 'live'
            )
            SELECT e.id            AS event_id,
                   e.external_ref,
                   bk.name         AS bookmaker,
                   e.home_team, e.away_team,
                   e.home_score, e.away_score,
                   e.period_code, e.clock_seconds,
                   p.code          AS period,
                   s.id            AS selection_id,
                   s.side, s.line_value,
                   v.odds
            FROM canon c
            JOIN events e ON e.id = c.id
            JOIN bookmakers bk ON bk.id = e.bookmaker_id
            JOIN markets m     ON m.event_id = e.id
            JOIN periods p     ON p.id = m.period_id
            JOIN selections s  ON s.market_id = m.id
            JOIN v_current_odds v ON v.selection_id = s.id
            WHERE c.rn = 1
              AND s.is_open = true
            ORDER BY c.match_id, p.ordinal, s.side
            """
        )
    return {"events": [dict(r) for r in rows]}


@app.get("/stream")
async def stream():
    """SSE: live push of board/compare changes (EventSource)."""
    return StreamingResponse(
        realtime.stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/books")
async def books():
    """Registered bookmakers (read side — powers the compare matrix header)."""
    return {"books": await compare.books(app.state.pool)}


@app.get("/markets")
async def markets():
    """Market types with live data (powers the compare market tabs)."""
    return {"markets": await compare.markets(app.state.pool)}


@app.get("/compare")
async def compare_board(period: str = "ft", market_type: str = "total_points"):
    """Same market across books: per matched game, per book line + odds, best per side."""
    return {"matches": await compare.compare(app.state.pool, period, market_type)}


# --------------------------------------------------------------------------- #
# Ingest
# --------------------------------------------------------------------------- #

@app.post("/ingest", status_code=201)
async def ingest_tick(payload: schemas.IngestPayload):
    """Accept one normalized scrape tick; upsert + append-only dedupe."""
    try:
        result = await ingest.apply(app.state.pool, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    realtime.notify("ingest")  # push to connected wallboards
    return result


# --------------------------------------------------------------------------- #
# Remote bet placement (TB-003)
# --------------------------------------------------------------------------- #

@app.post("/bets", dependencies=[Depends(require_bet_token)])
async def place_bet(payload: schemas.BetIn, response: Response):
    try:
        bet, created = await bets.place(app.state.pool, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.status_code = 201 if created else 200
    return bet


@app.get("/bets", dependencies=[Depends(require_bet_token)])
async def list_bets():
    return {"bets": await bets.list_bets(app.state.pool)}


@app.post("/bets/{bet_id}/cancel", dependencies=[Depends(require_bet_token)])
async def cancel_bet(bet_id: int):
    try:
        return await bets.cancel(app.state.pool, bet_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="bet not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/bridge/commands", dependencies=[Depends(require_bet_token)])
async def bridge_commands(bookmaker: str = "pokerbet"):
    return {"commands": await bets.commands(app.state.pool, bookmaker)}


@app.post("/bridge/report", dependencies=[Depends(require_bet_token)])
async def bridge_report(payload: schemas.BridgeReportIn):
    try:
        return await bets.report(app.state.pool, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="bet not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/bets-ui", response_class=HTMLResponse)
async def bets_ui():
    """Minimal control page (full wallboard integration lands in Phase D)."""
    return _BETS_HTML
