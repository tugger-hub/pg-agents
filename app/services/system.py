"""
Service layer for managing system-wide configuration and state.

This module provides functions to interact with the `system_configuration`
table in the database, which stores dynamic settings like the global
kill switch and loss limits.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

import psycopg

from app.models import SystemConfiguration

logger = logging.getLogger(__name__)

# --- In-memory Cache ---
_config_cache: Optional[SystemConfiguration] = None
_cache_expiry: Optional[datetime] = None
CACHE_TTL_SECONDS = 15

def get_system_configuration(db_conn: psycopg.Connection) -> Optional[SystemConfiguration]:
    """
    Fetches the system configuration from the database.

    Uses a simple in-memory cache to avoid frequent DB queries. The cache
    invalidates after CACHE_TTL_SECONDS.
    """
    global _config_cache, _cache_expiry

    if _config_cache and _cache_expiry and datetime.utcnow() < _cache_expiry:
        return _config_cache

    try:
        with db_conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, is_trading_enabled, daily_loss_limit_usd, weekly_loss_limit_usd, updated_at FROM system_configuration WHERE id = 1"
            )
            row = cursor.fetchone()
            if row:
                config = SystemConfiguration(
                    id=row[0],
                    is_trading_enabled=row[1],
                    daily_loss_limit_usd=float(row[2]),
                    weekly_loss_limit_usd=float(row[3]),
                    updated_at=row[4],
                )
                _config_cache = config
                _cache_expiry = datetime.utcnow() + timedelta(seconds=CACHE_TTL_SECONDS)
                logger.info("System configuration cache refreshed.")
                return config
            else:
                logger.error("System configuration not found in the database (id=1).")
                return None
    except Exception as e:
        logger.exception(f"Error fetching system configuration: {e}")
        return None

def set_trading_enabled(db_conn: psycopg.Connection, status: bool) -> bool:
    """
    Updates the trading status (kill switch) in the database.
    """
    global _config_cache, _cache_expiry
    try:
        with db_conn.cursor() as cursor:
            cursor.execute(
                "UPDATE system_configuration SET is_trading_enabled = %s, updated_at = %s WHERE id = 1",
                (status, datetime.utcnow()),
            )
            db_conn.commit()
            # Invalidate the cache immediately
            _config_cache = None
            _cache_expiry = None
            logger.warning(
                f"Trading has been globally {'ENABLED' if status else 'DISABLED'}."
            )
            return True
    except Exception as e:
        logger.exception(f"Failed to set trading status to {status}: {e}")
        db_conn.rollback()
        return False
