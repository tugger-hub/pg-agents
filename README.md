# pg-agents

Python implementation of the PG Solo-Lite auto-trading stack. The project bundles
single-process agents for data ingestion, strategy evaluation, order execution,
risk management, KPI snapshots, and Telegram notifications. Everything runs off
PostgreSQL with the schema defined in `db/schema_core.sql`.

## Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Docker (optional, required for integration tests via testcontainers)
- Telegram bot token (optional, only if you want notifications)

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure

1. Copy the template and adjust values:
   ```bash
   cp .env.template .env
   ```
2. Review `configs/strategy.yaml`. This file contains:
   - Symbols to trade
   - Exchange configuration (id, sandbox mode, etc.)
   - Strategy parameters (EMA pullback, volume breakout, divergence, retest, MACD)
   - Strategy toggles (`strategy.switches`) to enable/disable individual playbooks
   - Notification chat ids

Environment variables override YAML values. Nested keys use `__`, e.g.
`STRATEGY__SIGNAL_CONFIDENCE__THRESHOLD=0.8`.

## Database Setup

1. Create the target database (`pg_agents` by default).
2. Apply schema(s):
   ```bash
   psql "$DATABASE_URL" -f db/schema_core.sql
   # Optional modules (inbound dedupe, funding rates, etc.)
   psql "$DATABASE_URL" -f db/schema_plus_options.sql
   ```
3. Seed reference rows if you plan to run strategies immediately (instruments,
   exchange instruments, telegram chats). The integration tests provide good
   SQL examples under `tests/integration`.

## Running the stack

```bash
source .venv/bin/activate
python -m app.scheduler
```

The scheduler orchestrates the following loop every minute by default:

1. Fetch fresh candles via `IngestionAgent` (ccxt)
2. Run `StrategyAgent` (MA pullback, volume breakout, RSI divergence, breakout retest, optional MACD)
3. Submit resulting orders through `ExecutionAgent`
4. Risk checks (`RiskAgent`) every 30 seconds
5. KPI snapshots every 5 minutes
6. Hourly KPI report (Telegram)

Enable live trading by setting `EXCHANGE__ENABLE_LIVE_TRADING=true` **and**
providing API credentials. When disabled, orders are logged to the database only.

## Testing

Unit tests (fast):
```bash
pytest tests/unit
```

Full integration and DB tests (requires Docker):
```bash
pytest
```

## Operational Notes

- `RUNBOOK.md` documents operating procedures and failure handling.
- Notifications require `TELEGRAM_BOT_TOKEN` and chat ids inserted into
  `telegram_chats` (or set in config for convenience).
- If you add symbols, make sure they exist in both `instruments` and
  `exchange_instruments` tables with appropriate trading rules.

For more detail on architecture and database design see `PG_Solo_Lite_AGENTS.md`
and `PG_Solo_Lite_Design_DB_v2.0.md`.
