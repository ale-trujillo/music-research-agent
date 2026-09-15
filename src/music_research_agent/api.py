"""HTTP layer over the existing pipeline.

Nothing here decides anything. Search, discovery, comparison and reporting all
live in their own modules and are unaware of the web; this file only exposes
them. Keeping it that way is what lets the CLI and the interface stay in step,
and what lets the storage swap for a deployed key-value store without any of
the domain code noticing.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .analysis.engine import AnalysisEngine
from .assemble import Assembler
from .catalogue import Concentration
from .collect import collect
from .compare import Comparison, compare
from .discover import expand
from .evidence import Evidence
from .identify import looks_like_url, parse_reference
from .render import render
from .resolve import resolve
from .schema import ArtistReport, AudienceShape, Identity
from .search import ArtistHit, search_artists
from .profile import ArtistProfile, Link, build_profile
from .shape import build_shape
from .store import Favorite, open_store, storage_is_durable
from .triage import Triaged, triage

load_dotenv()

app = FastAPI(title="Music Research Agent", version="0.1.0")
store = open_store()
STATIC = Path(__file__).parent / "static"


class SaveRequest(BaseModel):
    query: str
    note: str | None = None


# Everything in this service is free to run except report generation, which
# spends real money per call. A public URL with an unguarded spend endpoint is
# an open tab on someone else's account, so that one endpoint — and only that
# one — can be put behind a shared secret. Set REPORT_TOKEN to turn it on;
# unset, the service behaves as it does locally.
def require_report_token(x_report_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("REPORT_TOKEN")
    if expected and x_report_token != expected:
        raise HTTPException(
            401,
            "Report generation is the only paid action here and is protected on this "
            "deployment. Everything else — search, artist pages, comparison, discovery "
            "— is open and costs nothing.",
        )


class ReportResponse(BaseModel):
    report: ArtistReport
    markdown: str


class ArtistSummary(BaseModel):
    """Everything the free sources know, with no model involved.

    This is what a page should open with: instant, costs nothing, and enough to
    decide whether the artist is worth the thirty-five seconds and third of a
    dollar a full report takes.
    """

    identity: Identity
    profile: ArtistProfile
    shape: AudienceShape
    concentration: list[Concentration] = Field(
        default_factory=list,
        description="Play distribution per platform — one hit or a catalogue",
    )
    metrics: list[Evidence]
    sources_used: list[str]
    sources_absent: list[str]
    saved: bool = Field(default=False, description="Already in favorites")


@app.get("/api/search", response_model=list[ArtistHit])
async def api_search(q: str = Query(min_length=1), limit: int = 8) -> list[ArtistHit]:
    """Search by name, or resolve a pasted profile link.

    A link has to be resolved rather than searched: handing Deezer a Spotify URL
    as a text query returns nothing, which reads to a user as "artist not found"
    when the artist was in fact perfectly identified.
    """
    if parse_reference(q) is not None:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            identity = await resolve(q, client)
            hit = ArtistHit(
                name=identity.resolved_name,
                deezer_id=identity.deezer_id or "",
                fans=0, releases=0,
                link=(f"https://www.deezer.com/artist/{identity.deezer_id}"
                      if identity.deezer_id else q),
            )
            if identity.deezer_id:
                detail = (await client.get(
                    f"https://api.deezer.com/artist/{identity.deezer_id}")).json()
                hit.fans = detail.get("nb_fan", 0)
                hit.releases = detail.get("nb_album", 0)
            return [hit]

    if looks_like_url(q):
        raise HTTPException(
            400,
            "That looks like a link but not one we recognise. Supported: Spotify, "
            "Deezer, YouTube, Apple Music, Last.fm, MusicBrainz artist pages.",
        )
    return await search_artists(q, limit=limit)


@app.get("/api/artist", response_model=ArtistSummary)
async def api_artist(query: str = Query(min_length=1)) -> ArtistSummary:
    """Free, instant metrics for one artist. No model, no cost."""
    bundle = await collect(query)
    if bundle.identity is None:
        raise HTTPException(404, f"could not resolve {query!r}")

    user_agent = os.getenv("MUSICBRAINZ_USER_AGENT", "music-research-agent/0.1")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        profile = await build_profile(bundle.identity, client, user_agent)
    for item in bundle.items:
        if item.key == "youtube.artist_channel" and item.citation.url:
            profile.links.append(Link(platform="YouTube", url=item.citation.url))

    saved = any(
        f.deezer_id and f.deezer_id == bundle.identity.deezer_id
        or f.name.casefold() == bundle.identity.resolved_name.casefold()
        for f in store.load()
    )
    return ArtistSummary(
        identity=bundle.identity,
        profile=profile,
        saved=saved,
        shape=build_shape(bundle),
        concentration=bundle.concentration,
        metrics=[i for i in bundle.items
                 if isinstance(i.value, int) and not isinstance(i.value, bool)],
        sources_used=bundle.sources_used,
        sources_absent=[f.source for f in bundle.sources_failed],
    )


@app.get("/api/health")
def api_health() -> dict[str, object]:
    """What the deployment can and cannot do right now."""
    return {
        "ok": True,
        "durable_favorites": storage_is_durable(),
        "report_protected": bool(os.getenv("REPORT_TOKEN")),
        "analysis_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        "sources": {
            name: bool(os.getenv(var)) for name, var in (
                ("spotify", "SPOTIFY_CLIENT_ID"), ("lastfm", "LASTFM_API_KEY"),
                ("youtube", "YOUTUBE_API_KEY"),
            )
        } | {"deezer": True, "musicbrainz": True},
    }


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
async def api_report(
    request: SaveRequest, _: None = Depends(require_report_token)
) -> ReportResponse:
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
