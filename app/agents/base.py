"""
Base class for all agents in the system.
"""
import abc

class Agent(abc.ABC):
    """
    Abstract base class for all agents. It defines the common interface that all
    agents must implement.
    """

    @abc.abstractmethod
    def run(self):
        """
        The main entry point for the agent's logic. This method is called by the
        scheduler.
        """
        raise NotImplementedError
