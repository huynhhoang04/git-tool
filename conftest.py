"""Make `git_tool` importable when pytest is collected from the key-router root."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
