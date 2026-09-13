"""Spotify. Identity anchor and discography -- not a metrics source.

Apps created under the current regime get an artist object with no followers,
no popularity and no genres, and a 403 on batch lookup, top-tracks and
related-artists. What still works is search and the album list, so that is all
this adapter claims.
"""

from __future__ import annotations

import base64
import os

import httpx

from ..evidence import Evidence
from ..schema import Confidence, Identity
from .base import SourceAdapter

API = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"
# Restricted apps 400 on any limit above 10; offset paging still works.
PAGE_SIZE = 10
MAX_RELEASES_PAGED = 100
_token: str | None = None


async def get_token(client: httpx.AsyncClient) -> str:
    global _token
    if _token:
        return _token
    cid, secret = os.getenv("SPOTIFY_CLIENT_ID"), os.getenv("SPOTIFY_CLIENT_SECRET")
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    r = await client.post(TOKEN_URL, headers={"Authorization": f"Basic {auth}"},
                          data={"grant_type": "client_credentials"})
    r.raise_for_status()
    _token = r.json()["access_token"]
    return _token


async def search_artists(client: httpx.AsyncClient, name: str, limit: int = 5) -> list[dict]:
    tok = await get_token(client)
    r = await client.get(f"{API}/search", headers={"Authorization": f"Bearer {tok}"},
                         params={"q": name, "type": "artist", "limit": limit})
    r.raise_for_status()
    return r.json().get("artists", {}).get("items", [])


class SpotifyAdapter(SourceAdapter):
    name = "spotify"
    requires_env = ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET")

    async def fetch(self, identity: Identity, client: httpx.AsyncClient) -> list[Evidence]:
        if not identity.spotify_id:
            return []
        tok = await get_token(client)
        headers = {"Authorization": f"Bearer {tok}"}
        url = f"https://open.spotify.com/artist/{identity.spotify_id}"

        releases, total = await self._all_albums(identity.spotify_id, client, headers)
        if not releases:
            return []

        out: list[Evidence] = [Evidence(
            key="spotify.release_count", value=total, unit="releases",
            confidence=Confidence.HIGH, citation=self.cite(url),
        )]
        releases.sort(key=lambda r: r[0], reverse=True)
        out.append(Evidence(
            key="spotify.latest_release", value=releases[0][0],
            confidence=Confidence.HIGH, citation=self.cite(url),
        ))
        for i, (when, title, kind) in enumerate(releases[:8], 1):
            out.append(Evidence(
                key=f"spotify.recent_release.{i}", value=f"{when} — {title} ({kind})",
                confidence=Confidence.HIGH, citation=self.cite(url),
            ))
        return out

    async def _all_albums(
        self, artist_id: str, client: httpx.AsyncClient, headers: dict
    ) -> tuple[list[tuple[str, str, str]], int]:
        """Page through the discography.

        Restricted apps reject any `limit` above 10 with a 400, but `offset`
        paging still works, so walk it 10 at a time.

        Transport failures are raised rather than swallowed. Returning an empty
        list on a 429 made the runner report "no data for this artist" when the
        truth was "we never got to ask" -- and those are different facts about
        an artist, not degrees of the same one. Now that reports cite absent
        sources, reporting the wrong reason puts a false statement under a
        citation.
        """
        releases: list[tuple[str, str, str]] = []
        total = 0
        offset = 0
        while offset <= MAX_RELEASES_PAGED:
            r = await client.get(
                f"{API}/artists/{artist_id}/albums", headers=headers,
                params={"limit": PAGE_SIZE, "offset": offset, "include_groups": "album,single"},
            )
            if r.status_code in (429, 500, 502, 503):
                raise RuntimeError(
                    f"rate limited or unavailable (HTTP {r.status_code}); "
                    "coverage gap is ours, not the artist's"
                )
            if r.status_code != 200:
                if offset == 0:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
                break
            data = r.json()
            total = data.get("total", total)
            items = data.get("items", [])
            releases += [
                (a["release_date"], a["name"], a.get("album_type", "release"))
                for a in items if a.get("release_date")
            ]
            if len(items) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        return releases, total
