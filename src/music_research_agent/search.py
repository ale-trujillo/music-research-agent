"""Artist search, proxied live rather than indexed.

There is no artist database to maintain here, deliberately. An index has to be
populated, reconciled and kept fresh, and the open option -- MusicBrainz --
covers emerging Latin American artists poorly: one of six on the acceptance set,
with confident wrong matches for the rest.

Deezer's catalogue is complete, current, unauthenticated and unmetered, so the
search box queries it directly. The catalogue stays Deezer's problem; we only
ever hold what a user actually looked up.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel

API = "https://api.deezer.com"
DEFAULT_LIMIT = 8
# Deezer's own ordering buries the obvious answer on a partial query: typing
# "susana" returned four collaborations with fewer than fifteen followers each
# and no sign of the artist anyone means. Over-fetch and re-rank instead.
OVERFETCH = 25


class ArtistHit(BaseModel):
    """One typeahead result, with enough to tell near-identical names apart."""

    name: str
    deezer_id: str
    fans: int
    releases: int
    picture: str | None = None
    link: str | None = None

    def label(self) -> str:
        return f"{self.name} — {self.fans:,} fans · {self.releases} releases"


async def search_artists(
    query: str, client: httpx.AsyncClient | None = None, limit: int = DEFAULT_LIMIT
) -> list[ArtistHit]:
    """Live typeahead against Deezer.

    Results keep their audience size, which is what lets a user distinguish the
    artist they meant from the famous one with a similar name -- the same signal
    the resolver uses, surfaced so a person can apply it too.
    """
    if not query.strip():
        return []
    owned = client is None
    client = client or httpx.AsyncClient(timeout=10)
    try:
        r = await client.get(
            f"{API}/search/artist", params={"q": query, "limit": max(limit, OVERFETCH)}
        )
        r.raise_for_status()
        data = r.json().get("data", [])
    finally:
        if owned:
            await client.aclose()

    hits = [
        ArtistHit(
            name=a["name"], deezer_id=str(a["id"]),
            fans=a.get("nb_fan", 0), releases=a.get("nb_album", 0),
            picture=a.get("picture_medium"), link=a.get("link"),
        )
        for a in data
    ]
    hits.sort(key=lambda h: _rank(h, query), reverse=True)
    return hits[:limit]


def _rank(hit: ArtistHit, query: str) -> tuple[int, int]:
    """How well a name answers what was typed, then how big the artist is.

    Name match dominates and audience only breaks ties, so typing a full name
    still surfaces the small artist who owns it rather than the famous one it
    resembles -- the same ordering the resolver uses, for the same reason.
    """
    name, q = hit.name.casefold(), query.casefold().strip()
    if name == q:
        match = 3
    elif name.startswith(q):
        match = 2
    elif q in name:
        match = 1
    else:
        match = 0
    return match, hit.fans
