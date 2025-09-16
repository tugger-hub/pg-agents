import logging

logger = logging.getLogger(__name__)

class ExecutionAgent:
    """
    Agent responsible for placing orders.
    """
    def __init__(self):
        pass

    def run(self):
        """
        The main loop for the agent, called periodically by the scheduler.
        """
        logger.info("ExecutionAgent running...")
