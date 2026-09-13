"""Identity resolution.

The rule that matters: candidates are ranked by name match first, never by
audience size. Probing the golden set, a short artist name returned the target
alongside a globally famous act with a near-identical prefix and roughly
200,000x the audience. Any "take the most popular result" resolver produces a
confident report about the wrong person.

When no exact match exists we still return the best candidate, but say so --
confidence drops and the rejected alternates travel with the report.
"""

from __future__ import annotations

import unicodedata

import httpx

import os

from .adapters import deezer, spotify
from .identify import PlatformRef, looks_like_url, parse_reference
from .schema import Confidence, Identity


def normalize(name: str) -> str:
    """Casefold and strip accents so 'Natalia' matches 'NATALIA'."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


async def resolve(
    query: str, client: httpx.AsyncClient, spotify_id_override: str | None = None
) -> Identity:
    """Resolve a name, or a pasted profile URL.

    A URL short-circuits everything below. The platform already made the
    identification, so there is no ranking to do and no chance of picking the
    wrong artist -- which is why pasting a link is the input to prefer.
    """
    if (ref := parse_reference(query)) is not None:
        return await _from_reference(ref, client)
    if looks_like_url(query):
        raise ValueError(
            f"that looks like a link but not one we recognise: {query[:80]}\n"
            "Supported: Spotify, Deezer, YouTube, Apple Music, Last.fm, MusicBrainz "
            "artist pages — or just type the artist's name."
        )

    target = normalize(query)
    alternates: list[str] = []

    try:
        dz = await deezer.search_artists(client, query, limit=5)
    except Exception:
        dz = []
    try:
        sp = await spotify.search_artists(client, query, limit=5)
    except Exception:
        sp = []

    dz_exact = [a for a in dz if normalize(a["name"]) == target]
    sp_exact = [a for a in sp if normalize(a["name"]) == target]

    # Record what we passed over, so a wrong resolution is visible rather than
    # silent. The audience figure is what makes a bad match obvious to a reader.
    for a in dz:
        if normalize(a["name"]) != target:
            alternates.append(f"{a['name']} (deezer, {a.get('nb_fan', 0)} fans)")
    for a in sp:
        if normalize(a["name"]) != target:
            alternates.append(f"{a['name']} (spotify)")

    if dz_exact and sp_exact:
        confidence = Confidence.HIGH
    elif dz_exact or sp_exact:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    dz_pick = dz_exact[0] if dz_exact else (dz[0] if dz else None)
    sp_pick = sp_exact[0] if sp_exact else (sp[0] if sp else None)

    if spotify_id_override:
        sp_pick = {"id": spotify_id_override, "name": query}
        confidence = Confidence.HIGH

    resolved_name = (
        (dz_exact or sp_exact or [dz_pick or sp_pick or {"name": query}])[0]
    )["name"]

    return Identity(
        resolved_name=resolved_name,
        spotify_id=sp_pick["id"] if sp_pick else None,
        deezer_id=str(dz_pick["id"]) if dz_pick else None,
        disambiguation_confidence=confidence,
        alternates_considered=alternates[:8],
    )


async def _from_reference(ref: PlatformRef, client: httpx.AsyncClient) -> Identity:
    """Turn a platform identifier into an identity, cross-linking the others.

    Whichever platform the link came from, the artist's name is read from that
    platform and used to find the matching profile elsewhere. The originating
    identifier is authoritative; the cross-links are best-effort.
    """
    name: str | None = None
    deezer_id: str | None = None
    spotify_id: str | None = None

    if ref.platform == "deezer":
        deezer_id = ref.id
        detail = (await client.get(f"https://api.deezer.com/artist/{ref.id}")).json()
        name = detail.get("name")
    elif ref.platform == "spotify":
        spotify_id = ref.id
        token = await spotify.get_token(client)
        r = await client.get(f"{spotify.API}/artists/{ref.id}",
                             headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 200:
            name = r.json().get("name")
    elif ref.platform == "youtube":
        name = await _youtube_title(ref, client)
    elif ref.platform in ("lastfm", "apple", "musicbrainz"):
        # These carry no name we can read back cheaply except Last.fm, whose
        # URL segment is the name itself.
        name = ref.id if ref.platform == "lastfm" else None

    if not name:
        raise ValueError(f"could not read an artist name from {ref.describe()}")

    if deezer_id is None:
        hits = await deezer.search_artists(client, name, limit=5)
        exact = [a for a in hits if normalize(a["name"]) == normalize(name)]
        if pick := (exact or hits):
            deezer_id = str(pick[0]["id"])
            # YouTube titles are whatever the artist typed -- one channel is
            # literally "susanacala". Music platforms carry the billed name, so
            # prefer theirs once the same artist is confirmed on both.
            if ref.platform == "youtube" and normalize(pick[0]["name"]) != normalize(name):
                if normalize(name).replace(" ", "") == normalize(pick[0]["name"]).replace(" ", ""):
                    name = pick[0]["name"]
    if spotify_id is None:
        try:
            found = await spotify.search_artists(client, name, limit=5)
            exact = [a for a in found if normalize(a["name"]) == normalize(name)]
            if pick := (exact or found):
                spotify_id = pick[0]["id"]
        except Exception:
            spotify_id = None

    return Identity(
        resolved_name=name,
        spotify_id=spotify_id,
        deezer_id=deezer_id,
        # The link identified the artist; nothing was ranked or guessed.
        disambiguation_confidence=Confidence.HIGH,
        alternates_considered=[f"resolved from {ref.describe()} — no ranking applied"],
    )


async def _youtube_title(ref: PlatformRef, client: httpx.AsyncClient) -> str | None:
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        return None
    params = {"key": key, "part": "snippet"}
    params["id" if ref.kind == "channel" else "forHandle"] = (
        ref.id if ref.kind == "channel" else f"@{ref.id}"
    )
    r = await client.get("https://www.googleapis.com/youtube/v3/channels", params=params)
    if r.status_code != 200:
        return None
    items = r.json().get("items", [])
    title = items[0]["snippet"]["title"] if items else None
    # "Artist - Topic" channels name the artist in the title; strip the suffix.
    return title.rsplit(" - Topic", 1)[0].strip() if title else None
