"""Who the artist is: the facts a reader needs before reading any analysis.

Biographical data is the thinnest thing in this stack. MusicBrainz is the only
free source with structured origin and birth information, and it covers roughly
one emerging Latin American artist in four -- so most of this card will say a
field could not be established, and says it rather than leaving a blank that
reads like zero.

The song count is summed from the actual tracklists instead of inferred. Deezer
publishes release counts, not track counts, and every cheaper proxy tried here
was wrong: its search endpoint returns nothing for an artist filter, and the top
tracks list caps out at the same number for artists of very different sizes.
"""

from __future__ import annotations

import asyncio
import time

import httpx
from pydantic import BaseModel, Field

from .resolve import normalize
from .schema import Identity

MUSICBRAINZ = "https://musicbrainz.org/ws/2/artist"
DEEZER = "https://api.deezer.com"
MAX_CONCURRENT = 6

# MusicBrainz allows one request a second and answers 503 past that. Two page
# loads in quick succession were enough to trip it, and the failure arrived
# looking exactly like "this artist is not in the database".
MB_MIN_INTERVAL_S = 1.1
MB_RETRIES = 3
_mb_last_call = 0.0
_mb_lock = asyncio.Lock()


class Link(BaseModel):
    platform: str
    url: str


class ArtistProfile(BaseModel):
    name: str
    kind: str | None = Field(default=None, description="Person or Group, per MusicBrainz")
    country: str | None = None
    origin: str | None = Field(default=None, description="City or area the artist is from")
    life_span_begin: str | None = Field(
        default=None,
        description="MusicBrainz life-span start. For a Person this is a birth date, "
        "for a Group a formation date — never a career start, which is why the label "
        "travels with it rather than being assumed.",
    )
    life_span_label: str | None = Field(
        default=None,
        description="'Born' for a person, 'Formed' for a group, 'Born or formed' when "
        "MusicBrainz records no type — the label is never inferred from the date",
    )
    first_release: str | None = Field(
        default=None,
        description="Earliest dated release in the catalogue — the closest honest proxy "
        "for when the artist started putting music out",
    )
    releases: int | None = None
    songs: int | None = Field(default=None, description="Summed from tracklists, not inferred")
    links: list[Link] = Field(default_factory=list)
    unestablished: list[str] = Field(
        default_factory=list,
        description="Fields no free source could fill — stated, not left blank",
    )
    biography_source: str = Field(
        default="unavailable",
        description="'found' when MusicBrainz covers this artist, 'not covered' when it "
        "answered and had nothing, 'unavailable' when it could not be reached. The "
        "third is not the second: one is a fact about the artist, the other about us.",
    )


async def build_profile(
    identity: Identity, client: httpx.AsyncClient, user_agent: str
) -> ArtistProfile:
    profile = ArtistProfile(name=identity.resolved_name)

    for platform, url in (
        ("Spotify", f"https://open.spotify.com/artist/{identity.spotify_id}" if identity.spotify_id else None),
        ("Deezer", f"https://www.deezer.com/artist/{identity.deezer_id}" if identity.deezer_id else None),
        ("Last.fm", f"https://www.last.fm/music/{identity.resolved_name.replace(' ', '+')}"),
    ):
        if url:
            profile.links.append(Link(platform=platform, url=url))

    if identity.deezer_id:
        await _deezer_counts(profile, identity.deezer_id, client)
    await _musicbrainz(profile, identity, client, user_agent)

    profile.unestablished = [
        label for label, value in (
            ("origin", profile.origin), ("country", profile.country),
            ("date of birth or formation", profile.life_span_begin),
            ("person or group", profile.kind),
        ) if not value
    ]
    return profile


async def _musicbrainz_get(
    client: httpx.AsyncClient, params: dict, user_agent: str
) -> httpx.Response | None:
    """One request a second, with retries. None means we never got an answer."""
    global _mb_last_call
    for attempt in range(MB_RETRIES):
        async with _mb_lock:
            wait = MB_MIN_INTERVAL_S - (time.monotonic() - _mb_last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            _mb_last_call = time.monotonic()
        try:
            response = await client.get(
                MUSICBRAINZ, headers={"User-Agent": user_agent}, params=params
            )
        except Exception:
            continue
        if response.status_code == 200:
            return response
        if response.status_code not in (429, 503):
            return None
        await asyncio.sleep(MB_MIN_INTERVAL_S * (attempt + 1))
    return None


async def _deezer_counts(
    profile: ArtistProfile, deezer_id: str, client: httpx.AsyncClient
) -> None:
    detail = (await client.get(f"{DEEZER}/artist/{deezer_id}")).json()
    profile.releases = detail.get("nb_album")

    albums = (await client.get(
        f"{DEEZER}/artist/{deezer_id}/albums", params={"limit": 100}
    )).json().get("data", [])
    if not albums:
        return

    # The earliest release is the closest thing to a career start that public
    # sources actually carry. It is a floor, not a fact: a catalogue can be
    # incomplete, and re-releases carry their reissue date.
    dated = sorted(a["release_date"] for a in albums if a.get("release_date"))
    profile.first_release = dated[0] if dated else None

    gate = asyncio.Semaphore(MAX_CONCURRENT)

    async def tracks(album_id: int) -> int:
        async with gate:
            try:
                return (await client.get(f"{DEEZER}/album/{album_id}")).json().get("nb_tracks", 0)
            except Exception:
                return 0

    counts = await asyncio.gather(*(tracks(a["id"]) for a in albums))
    profile.songs = sum(counts) or None


async def _musicbrainz(
    profile: ArtistProfile, identity: Identity, client: httpx.AsyncClient, user_agent: str
) -> None:
    """Origin and biography, for the minority of artists MusicBrainz covers.

    Only an exact name match is accepted. A fuzzy one here put a German festival
    against a Colombian artist at a perfect score, and biography is exactly the
    field where a wrong match is least likely to be noticed.
    """
    response = await _musicbrainz_get(
        client,
        {"query": f'artist:"{identity.resolved_name}"', "fmt": "json", "limit": 3},
        user_agent,
    )
    if response is None:
        # Leaving this as "not covered" would report our outage as a fact about
        # the artist, which is the recurring failure this codebase guards against.
        profile.biography_source = "unavailable"
        return

    candidates = response.json().get("artists", [])
    target = normalize(identity.resolved_name)
    match = next((a for a in candidates if normalize(a.get("name", "")) == target), None)
    if match is None:
        profile.biography_source = "not covered"
        return

    profile.biography_source = "found"

    profile.kind = match.get("type")
    profile.country = match.get("country")
    profile.origin = (match.get("begin-area") or match.get("area") or {}).get("name")
    profile.life_span_begin = (match.get("life-span") or {}).get("begin")
    profile.life_span_label = {
        "Person": "Born", "Group": "Formed", "Orchestra": "Formed", "Choir": "Formed",
        # Without a type we cannot tell a birth from a formation, and guessing
        # is what produced the mislabel this replaces.
    }.get(profile.kind, "Born or formed")
    if mbid := match.get("id"):
        profile.links.append(Link(platform="MusicBrainz", url=f"https://musicbrainz.org/artist/{mbid}"))
