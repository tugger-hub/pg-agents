import hashlib
import logging
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.config import get_settings
from app.models import TradingViewAlert

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_db_connection(request: Request):
    """
    Dependency to get a database connection from the pool.
    """
    pool = request.app.state.db_pool
    # The 'with' statement will automatically return the connection to the pool
    with pool.connection() as conn:
        yield conn


async def verify_token(x_auth_token: Annotated[str | None, Header()] = None):
    """
    Dependency to verify the webhook's authentication token.
    """
    settings = get_settings()
    if not settings.webhook_secret_token:
        logger.warning("WEBHOOK_SECRET_TOKEN is not set. Skipping webhook authentication.")
        return

    if not x_auth_token:
        logger.error("Missing X-Auth-Token header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Auth-Token header is missing",
        )

    if x_auth_token != settings.webhook_secret_token:
        logger.error("Invalid authentication token received.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )


from app.agents.execution import ExecutionAgent
from app.strategy_adapter import adapt_alert_to_decision


@router.post("/tradingview", dependencies=[Depends(verify_token)])
async def tradingview_webhook(
    alert: TradingViewAlert, db: psycopg.Connection = Depends(get_db_connection)
):
    """
    Handles incoming webhook alerts from TradingView.
    - Validates the payload using the TradingViewAlert model.
    - Stores the raw alert in the database and marks it for deduplication.
    - Adapts the alert to a trading decision.
    - Executes the decision by creating an order in the database.
    - Updates the alert status to 'parsed' or 'error'.
    """
    inbound_alert_id = None
    try:
        with db.cursor() as cur:
            # 1. Store the raw alert payload and get its ID
            raw_payload = alert.model_dump_json()
            cur.execute(
                """
                INSERT INTO inbound_alerts (source, dedupe_key, payload)
                VALUES (%s, %s, %s) RETURNING id
                """,
                ("tradingview", alert.idempotency_key, raw_payload),
            )
            result = cur.fetchone()
            if not result:
                raise Exception("Failed to insert inbound_alert and get ID.")
            inbound_alert_id = result[0]

            # 2. Mark the idempotency key as seen for deduplication
            payload_hash = hashlib.sha256(raw_payload.encode()).hexdigest()
            cur.execute(
                "SELECT mark_idem_seen(%s, %s, %s)",
                (alert.idempotency_key, payload_hash, "tradingview"),
            )

            # 3. Adapt the alert to a trading decision
            decision = adapt_alert_to_decision(alert)

            # 4. Execute the decision using the ExecutionAgent's logic
            execution_agent = ExecutionAgent(db_connection=db)
            order_id = execution_agent._execute_decision(decision)

            # 5. Update the inbound alert based on the outcome
            if order_id:
                cur.execute(
                    "UPDATE inbound_alerts SET parsed = true WHERE id = %s",
                    (inbound_alert_id,),
                )
                logger.info(f"Successfully processed webhook and created order {order_id}.")
            else:
                error_msg = "ExecutionAgent failed to create an order. Check logs for details."
                cur.execute(
                    "UPDATE inbound_alerts SET error = %s WHERE id = %s",
                    (error_msg, inbound_alert_id),
                )
                logger.error(f"Webhook {alert.idempotency_key}: {error_msg}")

            db.commit()
            return {"status": "ok", "key": alert.idempotency_key, "order_id": order_id}

    except psycopg.errors.UniqueViolation:
        logger.warning(f"Duplicate webhook received with key: {alert.idempotency_key}")
        db.rollback()
        return {"status": "duplicate", "key": alert.idempotency_key}
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        if db.is_usable() and inbound_alert_id:
            # If the alert was created but a later step failed, record the error.
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE inbound_alerts SET error = %s WHERE id = %s",
                    (str(e), inbound_alert_id),
                )
                db.commit()
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process webhook",
        )
