"""Ingest + bet contracts — normalized payloads at the API boundary.

The ingest contract is the integration point between the scraper layer and
the ingest API; the bet contract is the odds screen's remote-placement API.
Both are deliberately flat and bookmaker-agnostic.
"""
from datetime import datetime
from typing import Literal

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


class BetIn(BaseModel):
    """One bet request from the odds screen."""

    model_config = ConfigDict(extra="forbid")

    selection_id: int = Field(gt=0)
    stake: float = Field(gt=0, le=100_000)
    mode: Literal["manual", "auto"] = "manual"  # manual = user confirms on the book
    idempotency_key: str = Field(min_length=8, max_length=64)


class BridgeReportIn(BaseModel):
    """Status report from the bridge overlay."""

    model_config = ConfigDict(extra="forbid")

    bet_id: int = Field(gt=0)
    status: Literal["delivered", "confirmed", "failed"]
    reason: str | None = Field(default=None, max_length=500)
