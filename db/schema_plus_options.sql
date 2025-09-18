-- PG Solo-Lite DB Plus Optional Modules Schema (v2.0)
-- This schema is based on the design defined in PG_Solo_Lite_Design_DB_v2.0.md
-- It should be applied *after* the core schema.

-- Section 5.1: Message Stability Extension (Inbound Dedupe)
CREATE TABLE IF NOT EXISTS inbound_dedupe_keys (
  id BIGSERIAL PRIMARY KEY,
  idempotency_key VARCHAR(200) UNIQUE NOT NULL,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  source VARCHAR(50) NOT NULL,
  payload_hash VARCHAR(64) NOT NULL,
  processed BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE OR REPLACE FUNCTION mark_idem_seen(p_key text, p_hash text, p_src text)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO inbound_dedupe_keys(idempotency_key, payload_hash, source)
  VALUES (p_key, p_hash, p_src)
  ON CONFLICT (idempotency_key) DO
    UPDATE SET last_seen_at = NOW();
END $$;


-- Section 5.7: Pine Script Alert Reception (Optional)
-- External alert inbox for auditing/reprocessing
CREATE TABLE IF NOT EXISTS inbound_alerts (
  id BIGSERIAL PRIMARY KEY,
  source VARCHAR(50) NOT NULL DEFAULT 'tradingview',
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  dedupe_key VARCHAR(200),
  payload JSONB NOT NULL,
  parsed BOOLEAN NOT NULL DEFAULT FALSE,
  error TEXT
);

-- Optional dedupe index (excluding nulls)
CREATE UNIQUE INDEX IF NOT EXISTS ux_inbound_alerts_dedupe
  ON inbound_alerts(dedupe_key) WHERE dedupe_key IS NOT NULL;


-- Section 5.2: Fee, Funding & FX Rate Snapshots (Valuation/Settlement SoT)
CREATE TABLE IF NOT EXISTS exchange_fee_schedules (
  id SERIAL PRIMARY KEY,
  exchange_id INT NOT NULL REFERENCES exchanges(id),
  effective_from TIMESTAMPTZ NOT NULL,
  effective_to   TIMESTAMPTZ,
  fee_schema JSONB NOT NULL,
  UNIQUE(exchange_id, effective_from)
);

CREATE TABLE IF NOT EXISTS funding_rates (
  id BIGSERIAL PRIMARY KEY,
  exchange_instrument_id INT NOT NULL REFERENCES exchange_instruments(id),
  funding_time TIMESTAMPTZ NOT NULL,
  funding_rate NUMERIC NOT NULL,
  collected BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE(exchange_instrument_id, funding_time)
);

CREATE TABLE IF NOT EXISTS fx_rate_snapshots (
  ts TIMESTAMPTZ NOT NULL,
  base_ccy VARCHAR(10) NOT NULL,
  quote_ccy VARCHAR(10) NOT NULL,
  rate NUMERIC NOT NULL,
  PRIMARY KEY (ts, base_ccy, quote_ccy)
);
