"""HTTP layer over the existing pipeline.

Nothing here decides anything. Search, discovery, comparison and reporting all
live in their own modules and are unaware of the web; this file only exposes
them. Keeping it that way is what lets the CLI and the interface stay in step,
and what lets the storage swap for a deployed key-value store without any of
the domain code noticing.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analysis.engine import AnalysisEngine
from .assemble import Assembler
from .collect import collect
from .compare import Comparison, compare
from .discover import expand
from .render import render
from .schema import ArtistReport
from .search import ArtistHit, search_artists
from .store import Favorite, JsonFileStore
from .triage import Triaged, triage

load_dotenv()

app = FastAPI(title="Music Research Agent", version="0.1.0")
store = JsonFileStore()
STATIC = Path(__file__).parent / "static"


class SaveRequest(BaseModel):
    query: str
    note: str | None = None


class ReportResponse(BaseModel):
    report: ArtistReport
    markdown: str


@app.get("/api/search", response_model=list[ArtistHit])
async def api_search(q: str = Query(min_length=1), limit: int = 8) -> list[ArtistHit]:
    return await search_artists(q, limit=limit)


@app.get("/api/favorites", response_model=list[Favorite])
def api_favorites() -> list[Favorite]:
    return store.load()


@app.post("/api/favorites", response_model=Favorite)
async def api_save(request: SaveRequest) -> Favorite:
    """Saving captures today's figures, so a second save produces a trend."""
    bundle = await collect(request.query)
    if bundle.identity is None:
        raise HTTPException(404, f"could not resolve {request.query!r}")
    return store.add(bundle, note=request.note)


@app.delete("/api/favorites/{key}")
def api_forget(key: str) -> dict[str, bool]:
    if not store.remove(key):
        raise HTTPException(404, f"no saved artist matched {key!r}")
    return {"removed": True}


@app.get("/api/compare", response_model=Comparison)
def api_compare(names: str = Query(description="Comma-separated saved artist names")) -> Comparison:
    wanted = [n.strip().casefold() for n in names.split(",") if n.strip()]
    favorites = [f for f in store.load() if f.name.casefold() in wanted]
    if len(favorites) < 2:
        raise HTTPException(400, "pick at least two saved artists")
    return compare(favorites)


@app.get("/api/discover", response_model=list[Triaged])
async def api_discover(seeds: str | None = None, top: int = 20) -> list[Triaged]:
    """Expansion and triage cost nothing, so this endpoint is cheap to call."""
    seed_list = [s.strip() for s in seeds.split(",")] if seeds else store.seeds()
    if not seed_list:
        raise HTTPException(400, "no seeds — save some artists first")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        candidates = await expand(seed_list, client)
        return (await triage(candidates, client))[:top]


@app.post("/api/report", response_model=ReportResponse)
async def api_report(request: SaveRequest) -> ReportResponse:
    """The only expensive call here. Takes 35-80 seconds and costs about $0.35."""
    started = time.time()
    bundle = await collect(request.query)
    engine = AnalysisEngine(bundle)
    drafts = await engine.run_all()
    report = Assembler(bundle).build(
        drafts, run_id=uuid.uuid4().hex[:12],
        duration_s=time.time() - started, cost_usd=engine.cost_usd,
    )
    return ReportResponse(report=report, markdown=render(report))


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
