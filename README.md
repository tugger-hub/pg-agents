# pg-agents 🦾

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PostgreSQL 14+](https://img.shields.io/badge/postgresql-14+-blue.svg)](https://www.postgresql.org/)

An agentic, ultra-lightweight, low-complexity auto-trading framework designed for solo developers or small teams. The project bundles single-process asynchronous agents for data ingestion, strategy evaluation, order execution, risk management, and notification delivery, entirely orchestrated through PostgreSQL.

1인 또는 소규모 팀을 위한 초경량, 저복잡도 자동매매 멀티에이전트 프레임워크입니다. Python 비동기 스케줄러와 PostgreSQL 데이터베이스 제약을 결합하여 복잡한 브로커/메시지 큐 없이도 안전하고 신뢰할 수 있는 매매 파이프라인을 구동할 수 있도록 설계되었습니다.

---

## Why pg-agents? (Agentic & Safety-First Design)

Developing autonomous agents that perform financial transactions presents unique safety challenges. `pg-agents` addresses these challenges by shifting runtime safety checks into database-level constraints:

*   🤖 **Agentic Modular Architecture:** Decoupled into specialized single-purpose agents: `IngestionAgent` (market fetching), `StrategyAgent` (signal generation), `ExecutionAgent` (order placement), `RiskAgent` (stop-loss/risk checks), and `ReportAgent` (KPI tracking).
*   🛡️ **Safety & Idempotency by Design:** Designed to be highly compatible with AI-assisted software engineering (such as LLM agents). To prevent catastrophic double-ordering or state-desyncs, `pg-agents` enforces strict idempotency keys (`idempotency_key` with unique indices) and append-only ledgers at the schema level.
*   📦 **Zero-Broker Overhead:** Replaces complex message brokers (Celery, RabbitMQ) with simple database state polling and asynchronous task scheduling (`apscheduler`), drastically reducing infrastructure maintenance cost for solo maintainers.

---

## Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Docker (optional, required for integration tests via `testcontainers`)
- Telegram bot token (optional, only if you want notifications)

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

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

Environment variables override YAML values. Nested keys use `__`, e.g.
`STRATEGY__SIGNAL_CONFIDENCE__THRESHOLD=0.8`.

---

## Database Setup

1. Create the target database (`pg_agents` by default).
2. Apply schema(s):
   ```bash
   psql "$DATABASE_URL" -f db/schema_core.sql
   # Optional modules (inbound dedupe, funding rates, etc.)
   psql "$DATABASE_URL" -f db/schema_plus_options.sql
   ```
3. Seed reference rows if you plan to run strategies immediately (instruments, exchange instruments, telegram chats). The integration tests provide good SQL examples under `tests/integration`.

---

## Running the stack

```bash
source .venv/bin/activate
python -m app.scheduler
```

The scheduler orchestrates the following loop every minute by default:

1. Fetch fresh candles via `IngestionAgent` (`ccxt`)
2. Run `StrategyAgent` (MA pullback, volume breakout, RSI divergence, breakout retest, optional MACD)
3. Submit resulting orders through `ExecutionAgent`
4. Risk checks (`RiskAgent`) every 30 seconds
5. KPI snapshots every 5 minutes
6. Hourly KPI report (Telegram)

Enable live trading by setting `EXCHANGE__ENABLE_LIVE_TRADING=true` **and** providing API credentials. When disabled, orders are logged to the database only.

---

## Testing

Unit tests (fast):
```bash
pytest tests/unit
```

Full integration and DB tests (requires Docker):
```bash
pytest
```

---

## Operational Notes

- `RUNBOOK.md` documents operating procedures and failure handling.
- Notifications require `TELEGRAM_BOT_TOKEN` and chat ids inserted into `telegram_chats` (or set in config for convenience).
- If you add symbols, make sure they exist in both `instruments` and `exchange_instruments` tables with appropriate trading rules.

For more detail on architecture and database design see [PG_Solo_Lite_AGENTS.md](file:///C:/Users/hj/pg-agents/PG_Solo_Lite_AGENTS.md) and [PG_Solo_Lite_Design_DB_v2.0.md](file:///C:/Users/hj/pg-agents/PG_Solo_Lite_Design_DB_v2.0.md).

## License

This project is licensed under the MIT License - see the [LICENSE](file:///C:/Users/hj/pg-agents/LICENSE) file for details.
