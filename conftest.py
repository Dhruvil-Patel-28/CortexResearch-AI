"""Pytest root configuration — ensures the project root is importable."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
