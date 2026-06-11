"""
Common utility functions.
Ported from dgm_agent (V1) utils/common_utils.py
"""
import json


def read_file(file_path: str) -> str:
    """Read a file and return its contents as a string."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
    return content


def load_json_file(file_path: str) -> dict:
    """Load a JSON file and return its contents as a dictionary."""
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)
