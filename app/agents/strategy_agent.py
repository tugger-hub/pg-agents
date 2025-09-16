import logging

logger = logging.getLogger(__name__)

class StrategyAgent:
    """
    Agent responsible for generating trading signals.
    """
    def __init__(self):
        pass

    def run(self):
        """
        The main loop for the agent, called periodically by the scheduler.
        """
        logger.info("StrategyAgent running...")
