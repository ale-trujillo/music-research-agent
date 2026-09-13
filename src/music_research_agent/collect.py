"""Stage 1 of the pipeline: resolve, then fan out to every source.

Sources run in two waves. The first joins on stable IDs and can be trusted on
its own. The second identifies artists only by display name, so it runs after
and verifies candidates against what the first wave established.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import httpx

from .adapters.base import run_adapters, run_corroborating
from .adapters.deezer import DeezerAdapter
from .adapters.lastfm import LastfmAdapter
from .adapters.youtube import YouTubeAdapter
from .evidence import EvidenceBundle
from .resolve import resolve

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


CACHE_DIR = Path(".cache")
# A complete run is worth keeping for a day: these figures move slowly. A run
# where a source was down is worth keeping only long enough to iterate on
# prompts and rendering -- cache it for a day and the gap outlives the outage.
CACHE_TTL_COMPLETE_S = 24 * 60 * 60
CACHE_TTL_PARTIAL_S = 60 * 60


def _cache_path(query: str, spotify_id: str | None) -> Path:
    key = hashlib.sha256(f"{query.casefold()}|{spotify_id or ''}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{key}.json"


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

    if use_cache:
        CACHE_DIR.mkdir(exist_ok=True)
        path.write_text(bundle.model_dump_json())
    return bundle
