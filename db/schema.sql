-- ============================================================================
-- odds-screen — live basketball totals odds screen (SA bookmakers)
-- ============================================================================
-- v1 scope : live basketball, Total Points Over/Under markets only
--            (Q1, Q2, Q3, Q4, Full Game)
-- design   : generic market/period model — any sport, any market type,
--            any number of bookmakers can be added without schema changes
-- engine   : PostgreSQL 16+
--
-- Conventions:
--   * odds_history is APPEND-ONLY (one row per odds change). Line movement,
--     CLV, +EV and backtesting all derive from it later.
--   * A line change (e.g. 222.5 -> 223.5) creates a NEW selection row.
--     The old row keeps its history; the new row starts fresh.
--   * side is free text by design: 'over'/'under' for totals,
--     'home'/'away'/'draw' for moneylines later, etc.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ----------------------------------------------------------------------------
-- Reference / dimension tables (grow sideways, never reshaped)
-- ----------------------------------------------------------------------------

-- Bookmakers. v1: single BetConstruct source (PokerBet). Add rows for more books.
CREATE TABLE bookmakers (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code          text        NOT NULL UNIQUE,          -- 'pokerbet'
    name          text        NOT NULL,
    platform_type text        NOT NULL DEFAULT 'betconstruct', -- betconstruct|hollywoodbets|...
    is_active     boolean     NOT NULL DEFAULT true,
    meta          jsonb       NOT NULL DEFAULT '{}',
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- Sports. basketball now; soccer, tennis, etc. later.
CREATE TABLE sports (
    id   smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,        -- 'basketball'
    name text NOT NULL
);

-- Competitions / leagues.
CREATE TABLE competitions (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sport_id     smallint NOT NULL REFERENCES sports (id),
    external_ref text,                -- source-specific league id (nullable)
    name         text     NOT NULL,
    country      text,
    is_active    boolean  NOT NULL DEFAULT true,
    UNIQUE (sport_id, name)
);

-- Events (games). Event identity is source-scoped: one row per bookmaker.
-- Cross-book game matching (line shopping) is a later stage; it gets an
-- event_links table then — no changes needed here.
CREATE TABLE events (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    competition_id bigint      NOT NULL REFERENCES competitions (id),
    bookmaker_id   bigint      NOT NULL REFERENCES bookmakers (id),
    external_ref   text        NOT NULL,                -- source event id
    home_team      text        NOT NULL,
    away_team      text        NOT NULL,
    starts_at      timestamptz,
    status         text        NOT NULL DEFAULT 'scheduled', -- scheduled|live|ended|removed
    period_code    text,                                 -- q1|q2|q3|q4|ht|ft (live state)
    clock_seconds  smallint,                             -- seconds remaining in period
    home_score     smallint,
    away_score     smallint,
    last_seen_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (bookmaker_id, external_ref)
);
CREATE INDEX idx_events_live   ON events (status, period_code) WHERE status = 'live';
CREATE INDEX idx_events_lookup ON events (status, starts_at);

-- Periods. q1-q4 now; halves + full game seeded ready for Stage 3 markets.
CREATE TABLE periods (
    id      smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code    text    NOT NULL UNIQUE,    -- q1|q2|q3|q4|h1|h2|ft
    name    text    NOT NULL,           -- '1st Quarter' ...
    ordinal smallint NOT NULL           -- display/sort order
);
INSERT INTO periods (code, name, ordinal) VALUES
    ('q1', '1st Quarter', 1),
    ('q2', '2nd Quarter', 2),
    ('q3', '3rd Quarter', 3),
    ('q4', '4th Quarter', 4),
    ('h1', '1st Half',    5),
    ('h2', '2nd Half',    6),
    ('ft', 'Full Game',   7);

-- Market types. total_points now; moneyline, spread, team_total, props later.
CREATE TABLE market_types (
    id   smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,          -- 'total_points'
    name text NOT NULL
);
INSERT INTO market_types (code, name) VALUES ('total_points', 'Total Points');

-- ----------------------------------------------------------------------------
-- Markets & selections (the odds board)
-- ----------------------------------------------------------------------------

-- One market row per (event, period, market type): e.g. "Lakers v Celtics Q3 Total".
CREATE TABLE markets (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id       bigint      NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    period_id      smallint    NOT NULL REFERENCES periods (id),
    market_type_id smallint    NOT NULL REFERENCES market_types (id),
    status         text        NOT NULL DEFAULT 'open',  -- open|closed|settled|removed
    opened_at      timestamptz NOT NULL DEFAULT now(),
    closed_at      timestamptz,
    UNIQUE (event_id, period_id, market_type_id)
);
CREATE INDEX idx_markets_event ON markets (event_id);

-- One selection row per (market, bookmaker, side, line).
-- e.g. "Over 222.5 @ PokerBet". A line move = a new row.
CREATE TABLE selections (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_id    bigint   NOT NULL REFERENCES markets (id) ON DELETE CASCADE,
    bookmaker_id bigint   NOT NULL REFERENCES bookmakers (id),
    side         text     NOT NULL,          -- over|under (totals); home|away|draw (ML later)
    line_value   numeric(6,1),               -- NULL for non-line markets (moneyline)
    is_open      boolean  NOT NULL DEFAULT true,
    UNIQUE (market_id, bookmaker_id, side, line_value)
);
CREATE INDEX idx_selections_market ON selections (market_id);

-- ----------------------------------------------------------------------------
-- Time series (the history)
-- ----------------------------------------------------------------------------

-- Append-only odds history: one row per observed odds value per selection.
-- INSERT only on change (see ingest contract in the plan); events.last_seen_at
-- tracks liveness between ticks. Partition by captured_at when it grows.
CREATE TABLE odds_history (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    selection_id bigint      NOT NULL REFERENCES selections (id) ON DELETE CASCADE,
    odds         numeric(6,2) NOT NULL CHECK (odds >= 1.01),
    implied_prob numeric(5,4),              -- 1/odds, vig-included; computed at insert
    captured_at  timestamptz NOT NULL DEFAULT now(),
    source       text        NOT NULL DEFAULT 'scrape'  -- scrape|feed|manual
);
CREATE INDEX idx_odds_hist_sel_time ON odds_history (selection_id, captured_at DESC);
CREATE INDEX idx_odds_hist_time     ON odds_history (captured_at);

-- ----------------------------------------------------------------------------
-- Read model for the screen: latest odds per selection.
-- ----------------------------------------------------------------------------
CREATE VIEW v_current_odds AS
SELECT DISTINCT ON (s.id)
       s.id            AS selection_id,
       s.market_id,
       s.bookmaker_id,
       s.side,
       s.line_value,
       oh.odds,
       oh.captured_at
FROM selections s
JOIN odds_history oh ON oh.selection_id = s.id
ORDER BY s.id, oh.captured_at DESC, oh.id DESC;
