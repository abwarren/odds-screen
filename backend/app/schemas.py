"""Ingest contract — normalized payload from any scraper (v1: BetConstruct DOM).

The contract is the integration point between the scraper layer (Layer 1) and
the ingest API (Layer 2). It is deliberately flat and bookmaker-agnostic:
a scraper normalizes whatever DOM it reads into this shape, and the ingest
service handles upserts, line moves, and append-only dedupe.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SelectionIn(BaseModel):
    """One side of a market: 'over 222.5 @ 1.85'."""

    model_config = ConfigDict(extra="forbid")

    side: str  # 'over' | 'under' for totals; free text (home/away/draw) for later market types
    line_value: float | None = Field(default=None, ge=0)
    odds: float = Field(ge=1.01)  # decimal odds, schema CHECK odds >= 1.01
    source: str = "scrape"  # scrape|feed|manual


class MarketIn(BaseModel):
    """One market: an event × period × market-type, with its selections."""

    model_config = ConfigDict(extra="forbid")

    period: str  # q1|q2|q3|q4|h1|h2|ft (must exist in periods table)
    market_type: str = "total_points"
    status: str = "open"  # open|closed|settled|removed
    selections: list[SelectionIn] = Field(min_length=1)


class EventIn(BaseModel):
    """Live state + identity of one game at one bookmaker."""

    model_config = ConfigDict(extra="forbid")

    external_ref: str  # source event id (UNIQUE per bookmaker)
    competition: str
    sport: str = "basketball"
    home_team: str
    away_team: str
    starts_at: datetime | None = None
    status: str = "scheduled"  # scheduled|live|ended|removed
    period_code: str | None = None  # q1|q2|q3|q4|ht|ft (live state)
    clock_seconds: int | None = Field(default=None, ge=0, le=3600)
    home_score: int | None = Field(default=None, ge=0)
    away_score: int | None = Field(default=None, ge=0)


class IngestPayload(BaseModel):
    """Full normalized payload from one scrape tick of one bookmaker."""

    model_config = ConfigDict(extra="forbid")

    bookmaker: str  # bookmaker code, e.g. 'pokerbet' (upserted by code)
    event: EventIn
    markets: list[MarketIn] = Field(min_length=1)
