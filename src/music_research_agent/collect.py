"""Stage 1 of the pipeline: resolve, then fan out to every source."""

from __future__ import annotations

import httpx

from .adapters.base import run_adapters
from .adapters.deezer import DeezerAdapter
from .adapters.lastfm import LastfmAdapter
from .adapters.spotify import SpotifyAdapter
from .evidence import EvidenceBundle
from .resolve import resolve

ADAPTERS = [DeezerAdapter(), LastfmAdapter(), SpotifyAdapter()]


async def collect(query: str, spotify_id: str | None = None) -> EvidenceBundle:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        identity = await resolve(query, client, spotify_id)
        bundle = EvidenceBundle(artist_query=query, identity=identity)
        await run_adapters(ADAPTERS, identity, bundle, client)
        return bundle
