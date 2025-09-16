"""
The notification worker agent.
"""
import logging
import time
from datetime import datetime, timedelta

import psycopg
import telegram
from pydantic import ValidationError

from app.config import settings

logger = logging.getLogger(__name__)

class NotifyWorker:
    """
    A worker that fetches pending notifications from the database,
    sends them via Telegram, and updates their status.
    """
    MAX_RETRIES = 5
    BASE_BACKOFF_SECONDS = 60  # 1 minute

    def __init__(self, db_connection: psycopg.Connection):
        """
        Initializes the NotifyWorker.

        Args:
            db_connection: A psycopg3 database connection.
        """
        self.db_connection = db_connection
        if not settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set in the environment.")

        try:
            self.bot = telegram.Bot(token=settings.telegram_bot_token)
        except ValidationError as e:
            logger.error(f"Error initializing Telegram Bot: {e}")
            raise

    def _get_pending_notifications(self, cursor: psycopg.Cursor):
        """
        Fetches a batch of pending notifications from the outbox.

        This query is the core of the worker. It does the following:
        - Selects notifications that are 'PENDING'.
        - Only selects notifications that are due to be sent (`send_after`).
        - Joins with `telegram_chats` to ensure the target chat is enabled
          and the message severity meets the chat's minimum threshold.
        - Uses `FOR UPDATE SKIP LOCKED` to ensure that multiple worker
          instances don't pick up the same job.
        """
        query = """
            SELECT
                n.id, n.chat_id, n.title, n.message, n.fail_count
            FROM notification_outbox n
            JOIN telegram_chats tc ON n.chat_id = tc.chat_id
            WHERE
                n.status = 'PENDING'
                AND (n.send_after IS NULL OR n.send_after <= NOW())
                AND tc.enabled = TRUE
                AND n.severity >= tc.min_severity
            ORDER BY n.created_at
            LIMIT 10
            FOR UPDATE OF n SKIP LOCKED;
        """
        cursor.execute(query)
        return cursor.fetchall()

    def _send_message(self, chat_id: int, title: str, message: str) -> bool:
        """Sends a message using the Telegram bot."""
        try:
            full_message = f"*{title}*\n\n{message}"
            # In a real application, we would use asyncio for non-blocking calls.
            # For this simplified agent, a synchronous call is acceptable.
            self.bot.send_message(
                chat_id=chat_id,
                text=full_message,
                parse_mode=telegram.constants.ParseMode.MARKDOWN_V2
            )
            logger.info(f"Successfully sent notification to chat_id {chat_id}")
            return True
        except telegram.error.TelegramError as e:
            logger.error(f"Failed to send notification to chat_id {chat_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred while sending message to {chat_id}: {e}")
            return False

    def _update_notification_status(self, cursor: psycopg.Cursor, notification_id: int, success: bool):
        """Updates the notification status based on the send outcome."""
        if success:
            query = "UPDATE notification_outbox SET status = 'SENT', sent_at = NOW() WHERE id = %s;"
            cursor.execute(query, (notification_id,))
        else:
            # Get current fail_count first
            cursor.execute("SELECT fail_count FROM notification_outbox WHERE id = %s;", (notification_id,))
            fail_count = cursor.fetchone()[0]

            if fail_count + 1 >= self.MAX_RETRIES:
                status = 'FAILED'
                send_after = None
                logger.warning(f"Notification {notification_id} has reached max retries. Marking as FAILED.")
            else:
                status = 'PENDING'
                backoff_delay = self.BASE_BACKOFF_SECONDS * (2 ** fail_count)
                send_after = datetime.now() + timedelta(seconds=backoff_delay)
                logger.info(f"Notification {notification_id} failed. Retrying after {send_after}.")

            query = """
                UPDATE notification_outbox
                SET
                    status = %s,
                    fail_count = fail_count + 1,
                    send_after = %s
                WHERE id = %s;
            """
            cursor.execute(query, (status, send_after, notification_id))

    def run(self):
        """The main loop of the worker."""
        logger.debug("NotifyWorker running...")
        try:
            with self.db_connection.cursor() as cursor:
                # Using a transaction to ensure atomicity
                with cursor.connection.transaction():
                    notifications = self._get_pending_notifications(cursor)
                    if not notifications:
                        return

                    logger.info(f"Found {len(notifications)} pending notifications to send.")

                    for notif in notifications:
                        notif_id, chat_id, title, message, _ = notif
                        success = self._send_message(chat_id, title, message)
                        self._update_notification_status(cursor, notif_id, success)
        except psycopg.Error as e:
            logger.error(f"Database error in NotifyWorker: {e}")
            # The transaction will be rolled back automatically by the 'with' statement context manager
        except Exception as e:
            logger.error(f"An unexpected error occurred in NotifyWorker: {e}")
