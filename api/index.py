"""Vercel entry point.

The platform serves whatever ASGI app this module exposes as `app`. Everything
it needs is already in the package; this file only makes the package importable
from the repository root, since the source lives under `src/`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from music_research_agent.api import app  # noqa: E402

__all__ = ["app"]
