import asyncio
import logging

from app.logging import setup_logging
from app.scheduler import start_scheduler

# The logger should be retrieved after setup
setup_logging()
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("Starting application...")
    try:
        asyncio.run(start_scheduler())
    except KeyboardInterrupt:
        logger.info("Application shutting down.")
    except Exception as e:
        logger.critical(f"Application failed with an unhandled exception: {e}", exc_info=True)
