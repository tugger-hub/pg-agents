"""
Service layer for calculating and retrieving operational KPIs.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

import psycopg

from app.models import OpsKpiSnapshot

logger = logging.getLogger(__name__)


def calculate_realized_pnl_for_period(
    db_conn: psycopg.Connection, start_utc: datetime, end_utc: datetime
) -> float:
    """
    Calculates the sum of realized PnL from the transactions table over a given period.

    This includes transaction types that represent profit or loss, such as
    realized gains/losses, fees, and funding payments.

    Args:
        db_conn: An active database connection.
        start_utc: The start of the period (inclusive), timezone-aware (UTC).
        end_utc: The end of the period (exclusive), timezone-aware (UTC).

    Returns:
        The total realized PnL as a float. Returns 0.0 if no transactions found.
    """
    # These are the transaction types assumed to contribute to realized PnL.
    pnl_transaction_types = ("REALIZED_PNL", "FEE", "FUNDING")
    try:
        with db_conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(SUM(amount), 0.0)
                FROM transactions
                WHERE transaction_type = ANY(%s)
                  AND timestamp >= %s
                  AND timestamp < %s
                """,
                (list(pnl_transaction_types), start_utc, end_utc),
            )
            result = cursor.fetchone()
            pnl = float(result[0]) if result else 0.0
            logger.debug(f"Calculated PnL for {start_utc} to {end_utc}: {pnl:.2f}")
            return pnl
    except Exception as e:
        logger.exception(
            f"Error calculating PnL for period {start_utc} to {end_utc}: {e}"
        )
        return 0.0


def get_daily_pnl(db_conn: psycopg.Connection) -> float:
    """Calculates realized PnL for the current day (since midnight UTC)."""
    now_utc = datetime.now(timezone.utc)
    start_of_day_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    # The end time is exclusive, so using now_utc is correct.
    return calculate_realized_pnl_for_period(db_conn, start_of_day_utc, now_utc)


def get_weekly_pnl(db_conn: psycopg.Connection) -> float:
    """Calculates realized PnL for the current week (since Monday midnight UTC)."""
    now_utc = datetime.now(timezone.utc)
    start_of_week_utc = (now_utc - timedelta(days=now_utc.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # The end time is exclusive, so using now_utc is correct.
    return calculate_realized_pnl_for_period(db_conn, start_of_week_utc, now_utc)


def calculate_all_kpis(db_connection: psycopg.Connection) -> OpsKpiSnapshot:
    """
    Calculates all operational KPIs and returns them as a snapshot model.

    This is a placeholder implementation that returns dummy data. In a real
    scenario, this function would query the database (e.g., `orders`, `positions`
    tables) to compute the actual metrics.

    Args:
        db_connection: An active database connection.

    Returns:
        An OpsKpiSnapshot object populated with the latest KPIs.
    """
    logger.info("Calculating all operational KPIs (using placeholder data)...")

    # Placeholder logic: In a real implementation, you would run SQL queries here.
    # For example:
    # - latency: SELECT (updated_at - created_at) FROM orders WHERE status = 'FILLED' ...
    # - failure_rate: SELECT COUNT(*) FROM orders WHERE status = 'REJECTED' ...
    # - open_positions: SELECT COUNT(*) FROM positions WHERE quantity != 0 ...

    snapshot = OpsKpiSnapshot(
        ts=datetime.now(timezone.utc),
        order_latency_p50_ms=120,
        order_latency_p95_ms=350,
        order_failure_rate=0.02,
        order_retry_rate=0.05,
        position_gross_exposure_usd=50275.50,
        open_positions_count=3,
    )

    logger.info(f"KPI calculation complete: {snapshot.model_dump_json()}")
    return snapshot
