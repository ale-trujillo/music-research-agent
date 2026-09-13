"""Deezer. No credentials, and the strongest source we have for this use case.

Spotify's new-app regime strips followers, popularity and genres from the
artist object, so Deezer carries the audience metric and the genre signal
instead. Genre lives on albums rather than on the artist, so we aggregate it
across the discography.
"""

from __future__ import annotations

import collections

import httpx

from ..evidence import Evidence
from ..schema import Confidence, Identity
from .base import SourceAdapter

API = "https://api.deezer.com"
ALBUMS_SAMPLED_FOR_GENRE = 8


async def search_artists(client: httpx.AsyncClient, name: str, limit: int = 5) -> list[dict]:
    r = await client.get(f"{API}/search/artist", params={"q": name, "limit": limit})
    r.raise_for_status()
    return r.json().get("data", [])


class DeezerAdapter(SourceAdapter):
    name = "deezer"
    requires_env = ()  # open API

    async def fetch(self, identity: Identity, client: httpx.AsyncClient) -> list[Evidence]:
        if not identity.deezer_id:
            return []
        aid = identity.deezer_id
        link = f"https://www.deezer.com/artist/{aid}"
        out: list[Evidence] = []

        detail = (await client.get(f"{API}/artist/{aid}")).json()
        if (fans := detail.get("nb_fan")) is not None:
            out.append(Evidence(
                key="deezer.fans", value=fans, unit="fans",
                confidence=Confidence.HIGH,
                citation=self.cite(link, "stands in for Spotify popularity, which the API no longer exposes"),
            ))
        if (n_alb := detail.get("nb_album")) is not None:
            out.append(Evidence(
                key="deezer.release_count", value=n_alb, unit="releases",
                confidence=Confidence.HIGH, citation=self.cite(link),
            ))

        albums = (await client.get(f"{API}/artist/{aid}/albums", params={"limit": 50})).json().get("data", [])
        dated = sorted((a["release_date"] for a in albums if a.get("release_date")), reverse=True)
        if dated:
            out.append(Evidence(
                key="deezer.latest_release", value=dated[0],
                confidence=Confidence.HIGH, citation=self.cite(link),
            ))
            # Titles and formats, which Spotify used to supply at the cost of
            # four paginated calls against a quota that locks out for a day.
            # Deezer returns the whole discography in the call already made.
            titled = sorted(
                ((a["release_date"], a.get("title", "?"), a.get("record_type", "release"))
                 for a in albums if a.get("release_date")),
                reverse=True,
            )
            for i, (when, title, kind) in enumerate(titled[:8], 1):
                out.append(Evidence(
                    key=f"deezer.recent_release.{i}", value=f"{when} — {title} ({kind})",
                    confidence=Confidence.HIGH, citation=self.cite(link),
                ))
            out.append(Evidence(
                key="deezer.releases_last_12mo",
                value=sum(1 for d in dated if d >= _year_ago(dated[0])),
                unit="releases", confidence=Confidence.MEDIUM,
                citation=self.cite(link, "counted from dated releases"),
            ))

        # Genre is an album-level field on Deezer, so take the majority vote
        # across recent releases rather than trusting any single album tag.
        bag: collections.Counter[str] = collections.Counter()
        for album in albums[:ALBUMS_SAMPLED_FOR_GENRE]:
            det = (await client.get(f"{API}/album/{album['id']}")).json()
            for g in (det.get("genres") or {}).get("data", []):
                bag[g["name"]] += 1
        for genre, hits in bag.most_common(4):
            out.append(Evidence(
                key=f"deezer.genre.{genre.lower().replace(' ', '_')}", value=genre,
                confidence=Confidence.HIGH if hits > 1 else Confidence.MEDIUM,
                citation=self.cite(link, f"tagged on {hits} of {min(len(albums), ALBUMS_SAMPLED_FOR_GENRE)} sampled releases"),
            ))

        top = (await client.get(f"{API}/artist/{aid}/top", params={"limit": 5})).json().get("data", [])
        for i, t in enumerate(top, 1):
            out.append(Evidence(
                key=f"deezer.top_track.{i}", value=t["title"],
                confidence=Confidence.HIGH, citation=self.cite(link),
            ))

        # Deezer's related list skews heavily toward far larger artists, so it
        # is corroboration for comparables, never the source of them.
        related = (await client.get(f"{API}/artist/{aid}/related", params={"limit": 8})).json().get("data", [])
        for a in related:
            out.append(Evidence(
                key=f"deezer.related.{a['name']}", value=a.get("nb_fan", 0), unit="fans",
                confidence=Confidence.LOW,
                citation=self.cite(link, "Deezer related skews to much larger artists"),
            ))
        return out


def _year_ago(latest: str) -> str:
    try:
        return f"{int(latest[:4]) - 1}{latest[4:]}"
    except (ValueError, IndexError):
        return "0000"
