from typing import Dict, Any, Optional, List


def create_new_terminal(name: Optional[str] = None) -> str:
    """Creates a new terminal session and returns its ID"""
    pass

def run_terminal_command(terminal_id: str, command: str) -> bool:
    """Runs a command in the specified terminal session"""
    pass

def read_terminal_output(terminal_id: str, max_lines: int = 100) -> List[str]:
    """Returns the output from the specified terminal session"""
    pass
