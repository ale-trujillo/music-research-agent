"""Application entry point for deployment.

Vercel detects FastAPI natively and serves whatever `app` this module exposes,
so routing stays with the framework rather than being re-implemented in
`vercel.json` — an earlier attempt at manual rewrites fought that detection.

Only the import path needs arranging, since the package lives under `src/`.
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from music_research_agent.api import app  # noqa: E402

__all__ = ["app"]
