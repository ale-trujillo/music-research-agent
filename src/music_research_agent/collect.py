"""Stage 1 of the pipeline: resolve, then fan out to every source.

Sources run in two waves. The first joins on stable IDs and can be trusted on
its own. The second identifies artists only by display name, so it runs after
and verifies candidates against what the first wave established.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from datetime import UTC, datetime

import httpx

from .adapters.base import run_adapters, run_corroborating
from .adapters.deezer import DeezerAdapter
from .adapters.lastfm import LastfmAdapter
from .adapters.youtube import YouTubeAdapter
from .catalogue import Concentration, lastfm_concentration, youtube_concentration
from .evidence import Evidence, EvidenceBundle
from .resolve import resolve
from .schema import Citation, Confidence

# Spotify is deliberately not in the fan-out. Its remaining contribution was a
# dated discography, which Deezer returns in one unauthenticated call with no
# quota at all -- where Spotify needed four paginated calls against an
# allowance that, once spent, returns retry-after of about 22 hours. Extended
# quota is not a way out: since May 2025 Spotify grants it only to registered
# companies with 250k monthly active users, which no research tool will meet.
# It stays as the identity anchor in resolve(), one search per run.
ID_JOINED = [DeezerAdapter(), LastfmAdapter()]
NAME_MATCHED = [YouTubeAdapter()]
SOURCE_COUNT = len(ID_JOINED) + len(NAME_MATCHED)


# A deployed function only has /tmp, and that survives just as long as the
# instance does. Caching is an optimisation here, never correctness, so a
# read-only filesystem degrades to no cache rather than to an error.
CACHE_DIR = Path(os.getenv("CACHE_DIR", ".cache"))
# Bump whenever the shape of a collected bundle changes. Without it a pipeline
# change serves yesterday's structure for a day and looks like a bug in the new
# code: adding play-concentration returned empty for every cached artist.
CACHE_VERSION = 2
# A complete run is worth keeping for a day: these figures move slowly. A run
# where a source was down is worth keeping only long enough to iterate on
# prompts and rendering -- cache it for a day and the gap outlives the outage.
CACHE_TTL_COMPLETE_S = 24 * 60 * 60
CACHE_TTL_PARTIAL_S = 60 * 60


def _cache_path(query: str, spotify_id: str | None) -> Path:
    key = hashlib.sha256(f"{query.casefold()}|{spotify_id or ''}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"v{CACHE_VERSION}-{key}.json"


async def collect(
    query: str, spotify_id: str | None = None, use_cache: bool = True
) -> EvidenceBundle:
    """Resolve, then fan out to every source.

    Results are cached to disk for a day. Iterating on prompts and rendering
    means collecting the same artist over and over, and free APIs are not
    free of limits: this project spent its own Spotify allowance that way and
    got a 22-hour lockout for it. The evidence does not change between two
    runs an hour apart; the quota does.
    """
    path = _cache_path(query, spotify_id)
    if use_cache and path.exists():
        cached = EvidenceBundle.model_validate_json(path.read_text())
        ttl = CACHE_TTL_PARTIAL_S if cached.sources_failed else CACHE_TTL_COMPLETE_S
        if time.time() - path.stat().st_mtime < ttl:
            return cached

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        identity = await resolve(query, client, spotify_id)
        bundle = EvidenceBundle(artist_query=query, identity=identity)
        await run_adapters(ID_JOINED, identity, bundle, client)
        await run_corroborating(NAME_MATCHED, identity, bundle, client)
        await _add_concentration(bundle, client)

    if use_cache:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(bundle.model_dump_json())
        except OSError:
            pass
    return bundle


async def _add_concentration(bundle: EvidenceBundle, client: httpx.AsyncClient) -> None:
    """Whether the plays come from one song or from a catalogue.

    Runs last because it needs the YouTube channel the corroborating wave
    verified. Every report before this existed flagged the same gap -- a large
    view count that could be one outlier or a consistent base, with no way to
    tell. For an A&R reader that is most of the decision.
    """
    name = bundle.identity.resolved_name if bundle.identity else bundle.artist_query
    channel_url = next(
        (i.citation.url for i in bundle.items
         if i.key == "youtube.artist_channel" and i.value and i.citation.url), None
    )
    channel_id = channel_url.rsplit("/", 1)[-1] if channel_url else None

    found: list[Concentration] = []
    for label, task in (
        ("youtube", youtube_concentration(channel_id, name, client) if channel_id else None),
        ("lastfm", lastfm_concentration(name, client)),
    ):
        if task is None:
            continue
        try:
            result = await task
        except Exception:
            continue
        if result:
            found.append(result)
            bundle.concentration.append(result)

    for result in found:
        source = result.platform.lower().replace(".", "")
        # Each platform cites itself. Pointing Last.fm figures at a YouTube URL
        # makes a citation unverifiable, which defeats the point of having one.
        url = channel_url if source == "youtube" else (
            f"https://www.last.fm/music/{name.replace(' ', '+')}" if source == "lastfm" else None
        )
        cite = Citation(source=source, url=url,
                        retrieved_at=datetime.now(UTC), note=result.caveat)
        bundle.add(
            Evidence(key=f"{source}.top_work_share", value=result.top_share, unit="percent",
                     confidence=Confidence.HIGH, citation=cite),
            Evidence(key=f"{source}.top3_work_share", value=result.top3_share, unit="percent",
                     confidence=Confidence.HIGH, citation=cite),
            Evidence(key=f"{source}.catalogue_verdict", value=result.verdict,
                     confidence=Confidence.HIGH, citation=cite),
        )
        for i, work in enumerate(result.works[:5], 1):
            bundle.add(Evidence(
                key=f"{source}.work.{i}", value=f"{work.title} — {work.plays} {result.unit} ({work.share}%)",
                confidence=Confidence.HIGH, citation=cite,
            ))
