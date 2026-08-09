# Odds Screen

Realtime odds screen for South African bookmakers — live basketball Total
Points Over/Under wallboard (Q1–Q4 + Full Game), with append-only odds history
for later line-movement / CLV / +EV analysis.

**Status:** Planning (v1 plan + DB schema committed; no code yet)

- Plan: `docs/plans/2026-08-09-odds-screen-v1.md`
- Schema: `db/schema.sql`

Stack (house pattern): FastAPI + asyncpg + PostgreSQL (Docker Compose, mapped
ports) + vanilla JS/SVG wallboard. Data source v1: BetConstruct-based bookmaker
(PokerBet.co.za) via DOM scraping.
