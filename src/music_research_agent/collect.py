"""Stage 1 of the pipeline: resolve, then fan out to every source.

Sources run in two waves. The first joins on stable IDs and can be trusted on
its own. The second identifies artists only by display name, so it runs after
and verifies candidates against what the first wave established.
"""

from __future__ import annotations

import httpx

from .adapters.base import run_adapters, run_corroborating
from .adapters.deezer import DeezerAdapter
from .adapters.lastfm import LastfmAdapter
from .adapters.spotify import SpotifyAdapter
from .adapters.youtube import YouTubeAdapter
from .evidence import EvidenceBundle
from .resolve import resolve

ID_JOINED = [DeezerAdapter(), LastfmAdapter(), SpotifyAdapter()]
NAME_MATCHED = [YouTubeAdapter()]
SOURCE_COUNT = len(ID_JOINED) + len(NAME_MATCHED)


async def collect(query: str, spotify_id: str | None = None) -> EvidenceBundle:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        identity = await resolve(query, client, spotify_id)
        bundle = EvidenceBundle(artist_query=query, identity=identity)
        await run_adapters(ID_JOINED, identity, bundle, client)
        await run_corroborating(NAME_MATCHED, identity, bundle, client)
        return bundle
