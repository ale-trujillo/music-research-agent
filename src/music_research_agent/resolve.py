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

from .adapters import deezer, spotify
from .schema import Confidence, Identity


def normalize(name: str) -> str:
    """Casefold and strip accents so 'Natalia' matches 'NATALIA'."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


async def resolve(
    query: str, client: httpx.AsyncClient, spotify_id_override: str | None = None
) -> Identity:
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
