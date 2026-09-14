"""Grow a candidate pool from a handful of seeds.

Nobody types two hundred artist names. The list is grown: take three to five
artists an A&R already rates, pull each one's neighbours, and keep the ones in
the same league. Survivors become seeds for the next round, so the pool widens
every time the tool is used.

The economics matter more than the mechanism. Expansion and triage run entirely
on free APIs and deterministic arithmetic, so two hundred candidates cost
nothing to gather and nothing to rank. Only the handful that survive triage get
a full report. Screening two hundred artists is not a two-hundred-report
problem.
"""

from __future__ import annotations

import asyncio
import os

import httpx
from pydantic import BaseModel, Field

from .adapters import deezer
from .resolve import normalize, resolve

LASTFM_API = "https://ws.audioscrobbler.com/2.0/"

# A neighbour this much larger than the seed is a recommendation artifact, not
# a peer. Expanding from a 1,758-follower artist otherwise returns acts with
# 409,000 — the same ceiling the report's comparables section rejects.
TIER_CEILING = 10
MAX_CONCURRENT = 6


class Candidate(BaseModel):
    name: str
    deezer_id: str | None = None
    fans: int = 0
    releases: int = 0
    found_via: list[str] = Field(default_factory=list, description="Seeds that surfaced this artist")
    sources: list[str] = Field(default_factory=list, description="Which graphs agreed")

    @property
    def corroboration(self) -> int:
        """Appearing from several seeds, or in both graphs, is the real signal."""
        return len(set(self.found_via)) + len(set(self.sources)) - 1


async def _lastfm_similar(name: str, client: httpx.AsyncClient, limit: int = 20) -> list[str]:
    key = os.getenv("LASTFM_API_KEY")
    if not key:
        return []
    r = await client.get(LASTFM_API, params={
        "method": "artist.getSimilar", "artist": name, "api_key": key,
        "format": "json", "autocorrect": 1, "limit": limit,
    })
    if r.status_code != 200:
        return []
    return [a["name"] for a in (r.json().get("similarartists") or {}).get("artist", [])]


async def expand(
    seeds: list[str], client: httpx.AsyncClient, ceiling_multiple: int = TIER_CEILING
) -> list[Candidate]:
    """Neighbours of every seed, deduplicated and held to the seeds' league.

    Both graphs are queried because they fail differently: Deezer's related
    list returns nothing for the smallest artists, while Last.fm's similarity
    reaches further down the tail. Neither alone covers an emerging roster.
    """
    pool: dict[str, Candidate] = {}
    seed_ids: set[str] = set()
    largest_seed = 0

    for seed in seeds:
        identity = await resolve(seed, client)
        if identity.deezer_id:
            seed_ids.add(identity.deezer_id)
            detail = (await client.get(f"https://api.deezer.com/artist/{identity.deezer_id}")).json()
            largest_seed = max(largest_seed, detail.get("nb_fan", 0))

        for artist_name in await _lastfm_similar(identity.resolved_name, client):
            _record(pool, artist_name, seed, "lastfm")

        if identity.deezer_id:
            related = (await client.get(
                f"https://api.deezer.com/artist/{identity.deezer_id}/related",
                params={"limit": 25},
            )).json().get("data", [])
            for artist in related:
                entry = _record(pool, artist["name"], seed, "deezer")
                entry.deezer_id = str(artist["id"])
                entry.fans = artist.get("nb_fan", 0)
                entry.releases = artist.get("nb_album", 0)

    await _fill_missing(pool, client)

    ceiling = max(largest_seed * ceiling_multiple, 1_000)
    return sorted(
        (c for c in pool.values()
         if c.deezer_id and c.deezer_id not in seed_ids and c.fans <= ceiling),
        key=lambda c: (-c.corroboration, -c.fans),
    )


def _record(pool: dict[str, Candidate], name: str, seed: str, source: str) -> Candidate:
    entry = pool.setdefault(normalize(name), Candidate(name=name))
    entry.found_via.append(seed)
    entry.sources.append(source)
    return entry


async def _fill_missing(pool: dict[str, Candidate], client: httpx.AsyncClient) -> None:
    """Last.fm gives names only, so size has to be looked up before filtering."""
    missing = [c for c in pool.values() if c.deezer_id is None]
    gate = asyncio.Semaphore(MAX_CONCURRENT)

    async def lookup(candidate: Candidate) -> None:
        async with gate:
            try:
                hits = await deezer.search_artists(client, candidate.name, limit=3)
            except Exception:
                return
        exact = [a for a in hits if normalize(a["name"]) == normalize(candidate.name)]
        if pick := (exact or hits):
            candidate.deezer_id = str(pick[0]["id"])
            candidate.fans = pick[0].get("nb_fan", 0)
            candidate.releases = pick[0].get("nb_album", 0)

    await asyncio.gather(*(lookup(c) for c in missing))
