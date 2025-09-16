import logging

logger = logging.getLogger(__name__)

class IngestionAgent:
    """
    Agent responsible for fetching market data.
    """
    def __init__(self):
        pass

    def run(self):
        """
        The main loop for the agent, called periodically by the scheduler.
        """
        logger.info("IngestionAgent running...")
