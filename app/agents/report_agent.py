import logging

logger = logging.getLogger(__name__)

class ReportAgent:
    """
    Agent responsible for generating and sending reports.
    """
    def __init__(self):
        pass

    def run(self):
        """
        The main loop for the agent, called periodically by the scheduler.
        """
        logger.info("ReportAgent running...")
