from abc import ABC, abstractmethod
from typing import Tuple


class ISandbox(ABC):
    """
    Interface for Sandboxes to execute Python code safely.
    Decouples the execution environment (Local subprocess, Docker, Cloud VMs) from the Agent logic.
    """

    @abstractmethod
    def execute(self, code: str, task_id: str, timeout: int = 30) -> Tuple[bool, str]:
        """
        Executes the provided Python code.

        Args:
            code: The Python code to execute.
            task_id: A unique identifier for the execution task.
            timeout: Maximum execution time in seconds.

        Returns:
            A tuple (success, output).
            - success (bool): True if the code exited with 0, False otherwise.
            - output (str): The combined stdout and stderr, or traceback info.
        """
        pass
