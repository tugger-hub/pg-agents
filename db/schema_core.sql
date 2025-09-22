-- PG Solo-Lite DB Core Schema (v2.0) - Corrected
-- This schema is based on the design defined in PG_Solo_Lite_Design_DB_v2.0.md
-- with inferred core tables and functions to make it executable.

-- Section: Placeholder Functions for Normalization
CREATE OR REPLACE FUNCTION normalize_price(p_exchange_instrument_id INT, p_price NUMERIC)
RETURNS NUMERIC AS $$ BEGIN RETURN p_price; END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION normalize_size(p_exchange_instrument_id INT, p_quantity NUMERIC)
RETURNS NUMERIC AS $$ BEGIN RETURN p_quantity; END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION meets_min_notional(p_exchange_instrument_id INT, p_price NUMERIC, p_quantity NUMERIC)
RETURNS BOOLEAN AS $$ BEGIN RETURN TRUE; END; $$ LANGUAGE plpgsql;


-- Section: Core Table Definitions (Inferred)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS accounts (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id),
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exchanges (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS instruments (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) UNIQUE NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS exchange_instruments (
    id SERIAL PRIMARY KEY,
    exchange_id INT NOT NULL REFERENCES exchanges(id),
    instrument_id INT NOT NULL REFERENCES instruments(id),
    exchange_symbol VARCHAR(50) NOT NULL,
    trading_rules JSONB,
    UNIQUE(exchange_id, instrument_id),
    UNIQUE(exchange_id, exchange_symbol)
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'order_side') THEN
        CREATE TYPE order_side AS ENUM ('buy', 'sell');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'order_type') THEN
        CREATE TYPE order_type AS ENUM ('market', 'limit');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'order_status') THEN
        CREATE TYPE order_status AS ENUM ('NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED', 'REJECTED', 'EXPIRED');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    account_id INT NOT NULL REFERENCES accounts(id),
    exchange_instrument_id INT NOT NULL REFERENCES exchange_instruments(id),
    client_order_id VARCHAR(100) UNIQUE,
    exchange_order_id VARCHAR(100),
    idempotency_key VARCHAR(120),
    side order_side NOT NULL,
    type order_type NOT NULL,
    status order_status NOT NULL,
    price NUMERIC,
    quantity NUMERIC NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS executions (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id),
    price NUMERIC NOT NULL,
    quantity NUMERIC NOT NULL,
    fee NUMERIC,
    fee_currency VARCHAR(10),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,
    account_id INT NOT NULL REFERENCES accounts(id),
    related_order_id BIGINT REFERENCES orders(id),
    transaction_type VARCHAR(50) NOT NULL,
    amount NUMERIC NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    account_id INT NOT NULL REFERENCES accounts(id),
    exchange_instrument_id INT NOT NULL REFERENCES exchange_instruments(id),
    quantity NUMERIC NOT NULL DEFAULT 0,
    average_entry_price NUMERIC NOT NULL DEFAULT 0,
    initial_stop_loss NUMERIC, -- Critical for R-multiple calculation in RiskAgent
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_id, exchange_instrument_id)
);


-- Section 4.1: Order/Execution Core Integrity (from original design)
-- Note: The ALTER TABLE is no longer needed as the column is in CREATE TABLE.
-- ALTER TABLE orders ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120);

CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_idem_active
  ON orders(account_id, idempotency_key)
  WHERE status IN ('NEW','PARTIALLY_FILLED');

CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_exoid_active
  ON orders(exchange_order_id)
  WHERE status IN ('NEW','PARTIALLY_FILLED');

CREATE OR REPLACE FUNCTION trg_transactions_block_ud()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'transactions is append-only';
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_transactions_block_update ON transactions;
CREATE TRIGGER tr_transactions_block_update
  BEFORE UPDATE OR DELETE ON transactions
  FOR EACH ROW EXECUTE FUNCTION trg_transactions_block_ud();


-- Section 4.2: Order Normalization Trigger (from original design)
CREATE OR REPLACE FUNCTION trg_orders_normalize()
RETURNS trigger AS $$
BEGIN
  NEW.price := normalize_price(NEW.exchange_instrument_id, NEW.price);
  NEW.quantity := normalize_size(NEW.exchange_instrument_id, NEW.quantity);
  IF NOT meets_min_notional(NEW.exchange_instrument_id, NEW.price, NEW.quantity) THEN
    RAISE EXCEPTION 'min notional violation';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_orders_normalize ON orders;
CREATE TRIGGER tr_orders_normalize
  BEFORE INSERT OR UPDATE ON orders
  FOR EACH ROW EXECUTE FUNCTION trg_orders_normalize();


-- Section 4.3: Telegram Integration (from original design)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'alert_severity') THEN
    CREATE TYPE alert_severity AS ENUM ('INFO','WARN','CRITICAL');
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS telegram_chats (
  id SERIAL PRIMARY KEY,
  user_id INT REFERENCES users(id),
  chat_id BIGINT NOT NULL UNIQUE,
  description TEXT,
  min_severity alert_severity NOT NULL DEFAULT 'WARN',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notification_outbox (
  id BIGSERIAL PRIMARY KEY,
  channel VARCHAR(20) NOT NULL DEFAULT 'TELEGRAM',
  chat_id BIGINT NOT NULL,
  severity alert_severity NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  dedupe_key VARCHAR(120),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  send_after TIMESTAMPTZ,
  sent_at TIMESTAMPTZ,
  fail_count INT NOT NULL DEFAULT 0,
  status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_notification_outbox_dedupe
  ON notification_outbox(dedupe_key);

CREATE OR REPLACE FUNCTION enqueue_notification(
  p_chat_id BIGINT,
  p_sev alert_severity,
  p_title TEXT,
  p_msg TEXT,
  p_dedupe TEXT DEFAULT NULL
) RETURNS BIGINT AS $$
DECLARE v_id BIGINT;
BEGIN
  IF p_dedupe IS NOT NULL THEN
    INSERT INTO notification_outbox(chat_id, severity, title, message, dedupe_key)
    VALUES (p_chat_id, p_sev, p_title, p_msg, p_dedupe)
    ON CONFLICT (dedupe_key) DO NOTHING
    RETURNING id INTO v_id;
    RETURN COALESCE(v_id, 0);
  ELSE
    INSERT INTO notification_outbox(chat_id, severity, title, message)
    VALUES (p_chat_id, p_sev, p_title, p_msg)
    RETURNING id INTO v_id;
    RETURN v_id;
  END IF;
END; $$ LANGUAGE plpgsql;


-- Section 5.4: KPI Snapshots (from Plus optional module)
CREATE TABLE IF NOT EXISTS ops_kpi_snapshots (
  ts TIMESTAMPTZ PRIMARY KEY DEFAULT NOW(),
  order_latency_p50_ms INT,
  order_latency_p95_ms INT,
  order_failure_rate NUMERIC,
  order_retry_rate NUMERIC,
  position_gross_exposure_usd NUMERIC,
  open_positions_count INT
);


-- Section: System-wide Configuration for Guardrails (M10)
CREATE TABLE IF NOT EXISTS system_configuration (
    id INT PRIMARY KEY CHECK (id = 1),
    is_trading_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    daily_loss_limit_usd NUMERIC(15, 2) NOT NULL DEFAULT 1000.00,
    weekly_loss_limit_usd NUMERIC(15, 2) NOT NULL DEFAULT 3000.00,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Insert the default singleton configuration row if it doesn't exist.
INSERT INTO system_configuration (id) VALUES (1) ON CONFLICT (id) DO NOTHING;


-- Section: Market Data Storage (M3)
-- Note: A periodic cleanup job should be implemented to enforce data retention
-- policies (e.g., delete candles older than 30 days).
CREATE TABLE IF NOT EXISTS candles (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC NOT NULL,
    high NUMERIC NOT NULL,
    low NUMERIC NOT NULL,
    close NUMERIC NOT NULL,
    volume NUMERIC NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Unique constraint to prevent duplicate candle entries
CREATE UNIQUE INDEX IF NOT EXISTS ux_candles_symbol_tf_ts
    ON candles (symbol, timeframe, timestamp);

-- Index for efficient retrieval of recent candles for a symbol
CREATE INDEX IF NOT EXISTS idx_candles_symbol_timestamp
    ON candles (symbol, timestamp DESC);
