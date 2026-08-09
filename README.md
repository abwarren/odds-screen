# Odds Screen

Realtime odds screen for South African bookmakers — live basketball Total
Points Over/Under wallboard (Q1–Q4 + Full Game), with append-only odds history
for later line-movement / CLV / +EV analysis.

**Status:** TB-001 complete — ingest path live and QA-approved (vertical
slice 1 of the plan). Next: TB-002 BetConstruct scraper (Phase C).

- Plan: `docs/plans/2026-08-09-odds-screen-v1.md`
- Schema: `db/schema.sql`
- Tracer bullet evidence: `docs/tracer_bullets/TB-001/`
- Handoff: `SESSION_HANDOFF.md`

Stack (house pattern): FastAPI + asyncpg + PostgreSQL (Docker Compose, mapped
ports) + vanilla JS/SVG wallboard. Data source v1: BetConstruct-based bookmaker
(PokerBet.co.za) via DOM scraping.

## Run it

```bash
docker compose up -d --build          # db:5434, api:8002
curl localhost:8002/health            # {"status":"ok"}
.venv/bin/python -m pytest tests/ -v  # live-loopback acceptance suite
.venv/bin/python scripts/demo_tb001.py  # lifecycle demo
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness (SELECT 1) |
| `GET /board` | live events × open O/U selections (one query) |
| `POST /ingest` | normalized scrape tick → upserts + append-only history |

Ingest payload contract: `backend/app/schemas.py` — bookmaker code, event
(identity + live state), markets (period × market_type) with over/under
selections (line_value, decimal odds). Line moves close the old selection row
and start a new one; identical odds ticks append nothing.
