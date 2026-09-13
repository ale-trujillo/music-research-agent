"""Last.fm. Global listener counts, and our only generator of comparables.

A caveat that shapes how the output is used: at this tier the similarity score
is unreliable. Probing the golden set, one mid-size artist came back as a
perfect 1.0 match for three unrelated acts -- co-listening inside a small
shared audience, not musical similarity. So candidates are generated here and
must be corroborated elsewhere before the report calls them comparables.
"""

from __future__ import annotations

import os

import httpx

from ..evidence import Evidence
from ..schema import Confidence, Identity
from .base import SourceAdapter

API = "https://ws.audioscrobbler.com/2.0/"
UNRELIABLE_MATCH_THRESHOLD = 0.99


class LastfmAdapter(SourceAdapter):
    name = "lastfm"
    requires_env = ("LASTFM_API_KEY",)

    async def _call(self, client: httpx.AsyncClient, method: str, **kw) -> dict:
        r = await client.get(API, params={
            "method": method, "api_key": os.getenv("LASTFM_API_KEY"),
            "format": "json", "autocorrect": 1, **kw,
        })
        r.raise_for_status()
        return r.json()

    async def fetch(self, identity: Identity, client: httpx.AsyncClient) -> list[Evidence]:
        name = identity.resolved_name
        url = f"https://www.last.fm/music/{name.replace(' ', '+')}"
        out: list[Evidence] = []

        info = (await self._call(client, "artist.getInfo", artist=name)).get("artist") or {}
        stats = info.get("stats") or {}
        for field, unit in (("listeners", "listeners"), ("playcount", "plays")):
            if (raw := stats.get(field)) is not None:
                out.append(Evidence(
                    key=f"lastfm.{field}", value=int(raw), unit=unit,
                    confidence=Confidence.HIGH, citation=self.cite(url),
                ))

        for tag in (info.get("tags") or {}).get("tag", [])[:5]:
            out.append(Evidence(
                key=f"lastfm.tag.{tag['name'].lower().replace(' ', '_')}", value=tag["name"],
                confidence=Confidence.MEDIUM, citation=self.cite(url, "user-supplied tag"),
            ))

        similar = (await self._call(client, "artist.getSimilar", artist=name, limit=8))
        for a in (similar.get("similarartists") or {}).get("artist", []):
            match = float(a.get("match") or 0)
            # A perfect score on a long-tail artist means shared listeners, not
            # shared sound. Flag it rather than letting it read as certainty.
            note = ("match=1.0 on a small audience is a co-listening artifact"
                    if match >= UNRELIABLE_MATCH_THRESHOLD else None)
            out.append(Evidence(
                key=f"lastfm.similar.{a['name']}", value=round(match, 3),
                confidence=Confidence.LOW if note else Confidence.MEDIUM,
                citation=self.cite(url, note),
            ))
        return out
