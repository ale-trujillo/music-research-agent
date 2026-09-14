"""Rank candidates cheaply, before spending anything on reports.

Triage exists so that widening the funnel does not multiply the bill. Every
signal here comes from free APIs and is computed in code, so ranking two
hundred candidates costs nothing. Only survivors get a report.

What this is not: a judgement about an artist. It is an ordering over what can
be measured for free, and it is wrong in predictable ways -- it cannot see
Spotify, it rewards catalogue depth that may be self-released, and it treats a
Last.fm sample as though it represented a market. It sorts a queue. The report
is where anything gets decided.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date

import httpx
from pydantic import BaseModel, Field

from .discover import Candidate

LASTFM_API = "https://ws.audioscrobbler.com/2.0/"
MAX_CONCURRENT = 6

# Weights are ordering preferences, not measurements. Activity and engagement
# lead because they are the two things a small artist can demonstrate without a
# budget; raw size is discounted because at this tier it mostly reflects which
# platform the artist happens to be on.
WEIGHTS = {"activity": 3.0, "engagement": 3.0, "corroboration": 2.0, "reach": 1.0}


class Triaged(BaseModel):
    """A ranked candidate.

    Measurable signals are `None` when the source could not be reached, never
    zero. A failed request and a dormant artist produce identical numbers
    otherwise, and the ranking silently buries whoever we failed to fetch --
    one candidate scored 0 releases on one run and 8 on the next from a
    transient error alone.
    """

    name: str
    deezer_id: str | None
    score: float
    fans: int
    listeners: int | None = None
    releases_12mo: int | None = None
    plays_per_listener: float | None = None
    corroboration: int = 0
    reasons: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)

    def line(self) -> str:
        listeners = f"{self.listeners:>7,}l" if self.listeners is not None else "      ?l"
        releases = f"{self.releases_12mo}rel/12mo" if self.releases_12mo is not None else "?rel/12mo"
        depth = f"{self.plays_per_listener:>5.1f}p/l" if self.plays_per_listener is not None else "    ?p/l"
        return f"{self.name[:24]:<26}{self.score:>6.1f}  {self.fans:>7,}f {listeners}  {releases}  {depth}"


async def _profile(candidate: Candidate, client: httpx.AsyncClient) -> Triaged:
    listeners = playcount = None
    releases_12mo = None
    missing: list[str] = []

    if candidate.deezer_id:
        try:
            response = await client.get(
                f"https://api.deezer.com/artist/{candidate.deezer_id}/albums",
                params={"limit": 50},
            )
            response.raise_for_status()
            albums = response.json().get("data", [])
            cutoff = date.today().replace(year=date.today().year - 1).isoformat()
            releases_12mo = sum(1 for a in albums if (a.get("release_date") or "") >= cutoff)
        except Exception:
            missing.append("deezer releases")

    if key := os.getenv("LASTFM_API_KEY"):
        try:
            info = (await client.get(LASTFM_API, params={
                "method": "artist.getInfo", "artist": candidate.name,
                "api_key": key, "format": "json", "autocorrect": 1,
            })).json().get("artist") or {}
            stats = info.get("stats") or {}
            listeners = int(stats["listeners"]) if stats.get("listeners") else None
            playcount = int(stats["playcount"]) if stats.get("playcount") else None
        except Exception:
            missing.append("lastfm")
    else:
        missing.append("lastfm key")

    depth = round(playcount / listeners, 1) if listeners and playcount else None
    return Triaged(
        name=candidate.name, deezer_id=candidate.deezer_id, score=0.0,
        fans=candidate.fans, listeners=listeners, releases_12mo=releases_12mo,
        plays_per_listener=depth, corroboration=candidate.corroboration,
        missing=missing,
    )


def _score(t: Triaged) -> Triaged:
    """Bounded contributions, so one loud signal cannot carry a candidate.

    Dimensions we could not measure are dropped and the remaining weights
    renormalised, rather than scored as zero. Scoring an unreachable source as
    absence penalises the candidate for our outage.
    """
    parts: dict[str, float] = {"corroboration": min(t.corroboration / 3, 1.0)}
    if t.releases_12mo is not None:
        parts["activity"] = min(t.releases_12mo / 6, 1.0)
    if t.plays_per_listener is not None:
        parts["engagement"] = min(t.plays_per_listener / 12, 1.0)
    if t.listeners is not None:
        parts["reach"] = min(t.listeners / 5_000, 1.0)

    weight = sum(WEIGHTS[k] for k in parts)
    t.score = round(10 * sum(WEIGHTS[k] * v for k, v in parts.items()) / weight, 1)

    if t.releases_12mo is not None and t.releases_12mo >= 4:
        t.reasons.append(f"{t.releases_12mo} releases in 12 months — actively shipping")
    elif t.releases_12mo == 0:
        t.reasons.append("nothing released in 12 months")
    if t.plays_per_listener is not None and t.plays_per_listener >= 8:
        t.reasons.append(f"{t.plays_per_listener} plays per listener — the audience returns")
    if t.corroboration >= 3:
        t.reasons.append("surfaced from several seeds and both discovery graphs")
    if t.listeners is not None and t.listeners < 100:
        t.reasons.append(f"only {t.listeners} Last.fm listeners — near the floor of measurability")
    if t.missing:
        t.reasons.append(
            f"ranked on partial data — {', '.join(t.missing)} unavailable, "
            "those dimensions excluded rather than scored zero"
        )
    return t


async def triage(candidates: list[Candidate], client: httpx.AsyncClient) -> list[Triaged]:
    gate = asyncio.Semaphore(MAX_CONCURRENT)

    async def one(candidate: Candidate) -> Triaged:
        async with gate:
            return _score(await _profile(candidate, client))

    scored = await asyncio.gather(*(one(c) for c in candidates))
    return sorted(scored, key=lambda t: -t.score)
