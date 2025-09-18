import pytest
import psycopg
from testcontainers.postgres import PostgresContainer
from pathlib import Path
import json

# Define a fixture to manage the PostgreSQL container lifecycle.
# The 'scope="module"' ensures the container starts only once for all tests in this file.
@pytest.fixture(scope="module")
def postgres_db_url():
    """
    Spins up a PostgreSQL container, applies both core and plus schemas,
    and yields the connection URL. The container is torn down automatically.
    """
    # Locate schema files relative to this test file's location.
    sql_dir = Path(__file__).parent.parent.parent / "db"
    core_schema_path = sql_dir / "schema_core.sql"
    plus_schema_path = sql_dir / "schema_plus_options.sql"

    # The driver=None is crucial for psycopg3 compatibility
    with PostgresContainer("postgres:16-alpine", driver=None) as postgres:
        db_url = postgres.get_connection_url()
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                # Apply schemas
                cur.execute(core_schema_path.read_text())
                cur.execute(plus_schema_path.read_text())

                # Seed database with prerequisite data to satisfy foreign key constraints
                cur.execute("INSERT INTO users (username) VALUES ('test_user') RETURNING id;")
                user_id = cur.fetchone()[0]
                cur.execute("INSERT INTO accounts (user_id, name) VALUES (%s, 'test_account');", (user_id,))
                cur.execute("INSERT INTO exchanges (name) VALUES ('test_exchange') RETURNING id;")
                exchange_id = cur.fetchone()[0]
                cur.execute("INSERT INTO instruments (symbol) VALUES ('TEST/USD') RETURNING id;")
                instrument_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO exchange_instruments (exchange_id, instrument_id, exchange_symbol) VALUES (%s, %s, 'TESTUSD') RETURNING id;",
                    (exchange_id, instrument_id)
                )
                conn.commit()
        yield db_url

def test_inbound_dedupe_and_function(postgres_db_url):
    """Verify the inbound_dedupe_keys table and mark_idem_seen function."""
    with psycopg.connect(postgres_db_url) as conn:
        with conn.cursor() as cur:
            idem_key = "webhook-xyz-123"
            payload_hash = "abcde12345"
            source = "tradingview"

            # 1. Call the function to insert a key
            cur.execute("SELECT mark_idem_seen(%s, %s, %s);", (idem_key, payload_hash, source))
            conn.commit()

            # 2. Verify the key was inserted correctly
            cur.execute("SELECT source, payload_hash FROM inbound_dedupe_keys WHERE idempotency_key = %s;", (idem_key,))
            row = cur.fetchone()
            assert row is not None, "Dedupe key was not inserted."
            assert row[0] == source
            assert row[1] == payload_hash

            # 3. Verify the ON CONFLICT DO UPDATE part of the function
            cur.execute("SELECT mark_idem_seen(%s, %s, %s);", (idem_key, "new_hash", source))
            cur.execute("SELECT count(*) FROM inbound_dedupe_keys WHERE idempotency_key = %s;", (idem_key,))
            count = cur.fetchone()[0]
            assert count == 1, "Duplicate key was inserted instead of updated."

def test_inbound_alerts_table(postgres_db_url):
    """Verify we can insert and retrieve data from the inbound_alerts table."""
    with psycopg.connect(postgres_db_url) as conn:
        with conn.cursor() as cur:
            dedupe_key = "alert-id-456"
            payload = json.dumps({"signal": "buy", "price": 50000})
            cur.execute("INSERT INTO inbound_alerts (dedupe_key, payload, source) VALUES (%s, %s, 'test_source');", (dedupe_key, payload))
            conn.commit()

            cur.execute("SELECT payload->>'signal', source FROM inbound_alerts WHERE dedupe_key = %s;", (dedupe_key,))
            row = cur.fetchone()
            assert row is not None, "Alert was not inserted."
            assert row[0] == "buy"
            assert row[1] == "test_source"

def test_exchange_fee_schedules_table(postgres_db_url):
    """Verify we can insert and retrieve data from the exchange_fee_schedules table."""
    with psycopg.connect(postgres_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM exchanges WHERE name = 'test_exchange';")
            exchange_id = cur.fetchone()[0]
            fee_schema = json.dumps({"maker": "0.001", "taker": "0.002"})

            cur.execute("INSERT INTO exchange_fee_schedules (exchange_id, effective_from, fee_schema) VALUES (%s, NOW(), %s);", (exchange_id, fee_schema))
            conn.commit()

            cur.execute("SELECT fee_schema->>'taker' FROM exchange_fee_schedules WHERE exchange_id = %s;", (exchange_id,))
            taker_fee = cur.fetchone()[0]
            assert float(taker_fee) == 0.002

def test_funding_rates_table(postgres_db_url):
    """Verify we can insert and retrieve data from the funding_rates table."""
    with psycopg.connect(postgres_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM exchange_instruments WHERE exchange_symbol = 'TESTUSD';")
            exchange_instrument_id = cur.fetchone()[0]

            cur.execute("INSERT INTO funding_rates (exchange_instrument_id, funding_time, funding_rate) VALUES (%s, NOW(), %s);", (exchange_instrument_id, 0.00015))
            conn.commit()

            cur.execute("SELECT funding_rate FROM funding_rates WHERE exchange_instrument_id = %s;", (exchange_instrument_id,))
            rate = cur.fetchone()[0]
            assert float(rate) == 0.00015

def test_fx_rate_snapshots_table(postgres_db_url):
    """Verify we can insert and retrieve data from the fx_rate_snapshots table."""
    with psycopg.connect(postgres_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO fx_rate_snapshots (ts, base_ccy, quote_ccy, rate) VALUES (NOW(), 'CAD', 'USD', 0.73);")
            conn.commit()

            cur.execute("SELECT rate FROM fx_rate_snapshots WHERE base_ccy = 'CAD' AND quote_ccy = 'USD';")
            rate = cur.fetchone()[0]
            assert float(rate) == 0.73
