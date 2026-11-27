PRAGMA foreign_keys = ON;

CREATE TABLE assets (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    exchange TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
        CHECK (active IN (0, 1))
) STRICT;

CREATE TABLE candles (
    id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    interval_seconds INTEGER NOT NULL DEFAULT 86400
        CHECK (interval_seconds = 86400),
    open_time INTEGER NOT NULL,
    close_time INTEGER NOT NULL,
    open REAL NOT NULL CHECK (open > 0),
    high REAL NOT NULL CHECK (high > 0),
    low REAL NOT NULL CHECK (low > 0),
    close REAL NOT NULL CHECK (close > 0),
    volume REAL NOT NULL CHECK (volume >= 0),
    quote_volume REAL CHECK (quote_volume >= 0),
    source TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    CHECK (close_time = open_time + interval_seconds),
    CHECK (open_time % interval_seconds = 0),
    CHECK (high >= max(open, close, low)),
    CHECK (low <= min(open, close, high)),
    UNIQUE (asset_id, interval_seconds, open_time)
) STRICT;

CREATE TABLE model_versions (
    version TEXT PRIMARY KEY,
    architecture TEXT NOT NULL,
    window_size INTEGER NOT NULL CHECK (window_size > 0),
    feature_count INTEGER NOT NULL CHECK (feature_count > 0),
    model_path TEXT NOT NULL,
    model_sha256 TEXT NOT NULL CHECK (length(model_sha256) = 64),
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
) STRICT;

CREATE TABLE predictions (
    id INTEGER PRIMARY KEY,
    candle_id INTEGER NOT NULL REFERENCES candles(id),
    model_version TEXT NOT NULL
        REFERENCES model_versions(version),
    predicted_return REAL NOT NULL,
    predicted_price REAL NOT NULL CHECK (predicted_price > 0),
    emission_time INTEGER NOT NULL,
    target_open_time INTEGER NOT NULL,
    target_close_time INTEGER NOT NULL,
    inference_ms REAL CHECK (inference_ms >= 0),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    CHECK (target_close_time = target_open_time + 86400),
    CHECK (emission_time = target_open_time),
    UNIQUE (candle_id, model_version),
    UNIQUE (id, candle_id)
) STRICT;

CREATE TABLE portfolio (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL
        CHECK (mode IN ('PAPER_LIVE', 'REPLAY')),
    strategy TEXT NOT NULL
        CHECK (strategy IN ('LLM', 'MODEL_ONLY', 'BUY_HOLD')),
    currency TEXT NOT NULL DEFAULT 'USDT',
    initial_cash_micros INTEGER NOT NULL
        CHECK (initial_cash_micros > 0),
    cash_micros INTEGER NOT NULL CHECK (cash_micros >= 0),
    status TEXT NOT NULL DEFAULT 'PAUSED'
        CHECK (status IN ('ACTIVE', 'PAUSED', 'STOPPED')),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
) STRICT;

CREATE TABLE positions (
    id INTEGER PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolio(id),
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    quantity_sats INTEGER NOT NULL DEFAULT 0
        CHECK (quantity_sats >= 0),
    cost_basis_micros INTEGER NOT NULL DEFAULT 0
        CHECK (cost_basis_micros >= 0),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (portfolio_id, asset_id)
) STRICT;

CREATE TABLE risk_config (
    id INTEGER PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolio(id),
    version INTEGER NOT NULL CHECK (version > 0),
    max_exposure_bps INTEGER NOT NULL
        CHECK (max_exposure_bps BETWEEN 0 AND 10000),
    max_daily_loss_bps INTEGER NOT NULL
        CHECK (max_daily_loss_bps BETWEEN 0 AND 10000),
    max_data_age_seconds INTEGER NOT NULL
        CHECK (max_data_age_seconds > 0),
    min_order_micros INTEGER NOT NULL
        CHECK (min_order_micros > 0),
    fee_bps INTEGER NOT NULL
        CHECK (fee_bps BETWEEN 0 AND 10000),
    slippage_bps INTEGER NOT NULL
        CHECK (slippage_bps BETWEEN 0 AND 10000),
    prediction_threshold REAL NOT NULL
        CHECK (prediction_threshold > 0),
    emergency_stop INTEGER NOT NULL DEFAULT 0
        CHECK (emergency_stop IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (portfolio_id, version),
    UNIQUE (id, portfolio_id)
) STRICT;

CREATE TABLE agent_cycles (
    id INTEGER PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolio(id),
    candle_id INTEGER NOT NULL REFERENCES candles(id),
    prediction_id INTEGER,
    risk_config_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN (
            'PENDING', 'RUNNING', 'WAITING_EXECUTION',
            'COMPLETED', 'REJECTED', 'PAUSED', 'ERROR'
        )),
    attempts INTEGER NOT NULL DEFAULT 0
        CHECK (attempts >= 0),
    started_at INTEGER,
    finished_at INTEGER,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    FOREIGN KEY (prediction_id, candle_id)
        REFERENCES predictions(id, candle_id),
    FOREIGN KEY (risk_config_id, portfolio_id)
        REFERENCES risk_config(id, portfolio_id),
    UNIQUE (portfolio_id, candle_id)
) STRICT;

CREATE TABLE agent_decisions (
    id INTEGER PRIMARY KEY,
    cycle_id INTEGER NOT NULL UNIQUE REFERENCES agent_cycles(id),
    proposed_action TEXT NOT NULL
        CHECK (proposed_action IN ('BUY', 'HOLD', 'SELL')),
    authorized_action TEXT NOT NULL
        CHECK (authorized_action IN ('BUY', 'HOLD', 'SELL')),
    rationale TEXT NOT NULL,
    llm_model TEXT,
    llm_response TEXT,
    risk_approved INTEGER NOT NULL
        CHECK (risk_approved IN (0, 1)),
    risk_reason TEXT,
    latency_ms REAL CHECK (latency_ms >= 0),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    CHECK (risk_approved = 1 OR authorized_action = 'HOLD')
) STRICT;

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    decision_id INTEGER NOT NULL UNIQUE
        REFERENCES agent_decisions(id),
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN (
            'PENDING', 'FILLED', 'REJECTED', 'CANCELLED'
        )),
    quantity_sats INTEGER NOT NULL CHECK (quantity_sats > 0),
    price_micros INTEGER CHECK (price_micros > 0),
    notional_micros INTEGER CHECK (notional_micros > 0),
    fee_micros INTEGER NOT NULL DEFAULT 0
        CHECK (fee_micros >= 0),
    slippage_micros INTEGER NOT NULL DEFAULT 0
        CHECK (slippage_micros >= 0),
    execution_source TEXT,
    filled_at INTEGER,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    CHECK (
        status != 'FILLED'
        OR (
            price_micros IS NOT NULL
            AND notional_micros IS NOT NULL
            AND filled_at IS NOT NULL
            AND execution_source IS NOT NULL
        )
    )
) STRICT;

CREATE TABLE equity_history (
    id INTEGER PRIMARY KEY,
    cycle_id INTEGER NOT NULL REFERENCES agent_cycles(id),
    snapshot_type TEXT NOT NULL
        CHECK (snapshot_type IN ('EXECUTION', 'VALUATION')),
    cash_micros INTEGER NOT NULL CHECK (cash_micros >= 0),
    position_value_micros INTEGER NOT NULL
        CHECK (position_value_micros >= 0),
    equity_micros INTEGER NOT NULL CHECK (equity_micros >= 0),
    drawdown REAL NOT NULL CHECK (drawdown BETWEEN 0 AND 1),
    recorded_at INTEGER NOT NULL,
    CHECK (equity_micros = cash_micros + position_value_micros),
    UNIQUE (cycle_id, snapshot_type)
) STRICT;

CREATE TABLE system_logs (
    id INTEGER PRIMARY KEY,
    cycle_id INTEGER REFERENCES agent_cycles(id),
    level TEXT NOT NULL
        CHECK (level IN ('INFO', 'WARNING', 'ERROR')),
    component TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
) STRICT;

CREATE TABLE error_logs (
    id INTEGER PRIMARY KEY,
    cycle_id INTEGER REFERENCES agent_cycles(id),
    component TEXT NOT NULL,
    error_type TEXT NOT NULL,
    message TEXT NOT NULL,
    cause TEXT,
    corrective_action TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0
        CHECK (retry_count >= 0),
    resolved INTEGER NOT NULL DEFAULT 0
        CHECK (resolved IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    resolved_at INTEGER
) STRICT;

CREATE INDEX idx_cycles_status
ON agent_cycles(status);

CREATE INDEX idx_orders_status
ON orders(status);

CREATE INDEX idx_equity_time
ON equity_history(recorded_at);

CREATE INDEX idx_system_logs_time
ON system_logs(created_at);

CREATE INDEX idx_error_logs_resolved
ON error_logs(resolved);
