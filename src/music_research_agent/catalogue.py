"""How concentrated an artist's plays are: one hit, or a catalogue.

Every report this system has produced flagged the same unanswered question --
ten million views could be one outlier or a consistent base, and the headline
figures cannot tell you which. For an A&R reader that distinction is most of the
decision: a catalogue that performs is a signable artist, a single song that
performed is a licensing conversation.

Two free sources carry per-item figures. YouTube reports exact view counts per
video, and Last.fm reports playcounts per track from its own users. Neither
covers the other's platform, so both are reported separately rather than merged.

Variants are grouped before anything is measured. Last.fm lists "¿Cómo Pasó?",
"¿Cómo Pasó? - Con Joe Jonas" and "¿Cómo Pasó? Con Joe Jonas" as three tracks;
read naively the lead song looks like 43% of plays, and grouped it is 58%. The
naive reading understates hit concentration precisely where concentration is the
thing being measured.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections import defaultdict

import httpx
from pydantic import BaseModel, Field

YOUTUBE = "https://www.googleapis.com/youtube/v3"
LASTFM = "https://ws.audioscrobbler.com/2.0/"
PAGE = 50
MAX_ITEMS = 200

# Suffixes that mark a version of a song rather than a different song.
VARIANT = re.compile(
    r"\s*[-–(\[]?\s*\b("
    r"con |feat\.?|ft\.?|with |x |vs\.?|"
    r"official|video|oficial|lyric|visuali[sz]er|audio|pseudo|live|en vivo|"
    r"ac[uú]stico|acoustic|remix|version|versi[oó]n|remaster|cover|demo|sped up|slowed"
    r")\b.*$",
    re.IGNORECASE,
)
ARTIST_PREFIX = re.compile(r"^[^-–]{1,40}\s*[-–]\s*")


# One side may lack a space -- "Ela Taubert- TE PROMETO" is a real title. Both
# sides missing is a hyphenated word, which must not be split.
SEGMENT = re.compile(r"\s+[-–|·]\s*|\s*[-–|·]\s+")


def clean_title(title: str, artist: str | None = None) -> str:
    """The song name on its own, with original casing kept.

    Titles put the artist on either side of the separator -- "Artist - Song" and
    "Song - Artist x Guest | VISUALIZER" both occur on the same channel -- so
    this works by segment rather than by prefix. Dropping a prefix alone left a
    dangling "Song  - Artist" on the reversed form. The platform's own title
    stays on the tooltip, where the collaborator credit is still readable.
    """
    text = VARIANT.sub("", title.strip()).strip()
    if not artist:
        return text.strip(" -–|·") or title.strip()

    names = {artist.casefold()} | {w.casefold() for w in artist.split() if len(w) > 3}
    kept = []
    for segment in SEGMENT.split(text):
        piece = segment.strip(" -–|·,")
        if not piece:
            continue
        folded = piece.casefold()
        # A segment that is the artist, or a credit list opening with them, is
        # attribution rather than title.
        if folded in names or any(folded.startswith(n) and len(folded) < len(n) + 24
                                  for n in names):
            continue
        kept.append(piece)
    return " - ".join(kept).strip(" -–|·") or text.strip(" -–|·") or title.strip()


def canonical(title: str, artist: str | None = None) -> str:
    """Reduce a title to the song it is a version of."""
    text = unicodedata.normalize("NFKD", title)
    text = "".join(c for c in text if not unicodedata.combining(c))
    if artist and text.lower().startswith(artist.lower()):
        text = ARTIST_PREFIX.sub("", text, count=1)
    text = VARIANT.sub("", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.lower().split()) or title.lower()


class Work(BaseModel):
    title: str = Field(description="Song name alone, for the label")
    raw_title: str = Field(description="The platform's own title, kept for the tooltip")
    plays: int
    share: float = Field(description="Percent of the measured total")
    variants: int = Field(default=1, description="Versions grouped into this entry")


class Concentration(BaseModel):
    platform: str
    unit: str
    measured_total: int
    items_measured: int
    covers_everything: bool = Field(
        description="False when only part of the catalogue could be read"
    )
    works: list[Work] = Field(default_factory=list)
    top_share: float = 0.0
    top3_share: float = 0.0
    verdict: str = ""
    caveat: str | None = None


def _summarise(
    platform: str, unit: str, grouped: dict[str, tuple[str, int, int]],
    total: int, items: int, complete: bool, caveat: str | None,
    artist: str | None = None,
) -> Concentration:
    works = sorted(
        (Work(title=clean_title(title, artist), raw_title=title, plays=plays,
              share=round(plays / total * 100, 1), variants=n)
         for title, plays, n in grouped.values()),
        key=lambda w: -w.plays,
    ) if total else []

    top = works[0].share if works else 0.0
    top3 = round(sum(w.share for w in works[:3]), 1) if works else 0.0

    if not works:
        verdict = "nothing measurable"
    elif top >= 50:
        verdict = "one song carries the audience"
    elif top3 >= 75:
        verdict = "a few songs carry the audience"
    elif top3 >= 50:
        verdict = "led by a handful, with a real tail behind them"
    else:
        verdict = "spread across the catalogue"

    return Concentration(
        platform=platform, unit=unit, measured_total=total, items_measured=items,
        covers_everything=complete, works=works[:12],
        top_share=top, top3_share=top3, verdict=verdict, caveat=caveat,
    )


async def youtube_concentration(
    channel_id: str, artist: str, client: httpx.AsyncClient
) -> Concentration | None:
    key = os.getenv("YOUTUBE_API_KEY")
    if not key or not channel_id:
        return None

    channel = (await client.get(f"{YOUTUBE}/channels", params={
        "key": key, "id": channel_id, "part": "contentDetails,statistics"})).json()
    if not channel.get("items"):
        return None
    item = channel["items"][0]
    uploads = item["contentDetails"]["relatedPlaylists"]["uploads"]
    channel_total = int(item["statistics"].get("viewCount") or 0)

    # The recent page is not the catalogue: for one artist the 50 newest videos
    # held 11.9M views against a channel total of 492M. The hits sit further back.
    video_ids: list[str] = []
    token: str | None = None
    while len(video_ids) < MAX_ITEMS:
        params = {"key": key, "playlistId": uploads, "part": "contentDetails", "maxResults": PAGE}
        if token:
            params["pageToken"] = token
        page = (await client.get(f"{YOUTUBE}/playlistItems", params=params)).json()
        video_ids += [i["contentDetails"]["videoId"] for i in page.get("items", [])]
        if not (token := page.get("nextPageToken")):
            break

    grouped: dict[str, tuple[str, int, int]] = {}
    total = 0
    for start in range(0, len(video_ids), PAGE):
        batch = video_ids[start:start + PAGE]
        videos = (await client.get(f"{YOUTUBE}/videos", params={
            "key": key, "id": ",".join(batch), "part": "statistics,snippet"})).json().get("items", [])
        for video in videos:
            views = int(video["statistics"].get("viewCount") or 0)
            if not views:
                continue
            title = video["snippet"]["title"]
            slug = canonical(title, artist)
            label, plays, count = grouped.get(slug, (title, 0, 0))
            grouped[slug] = (label, plays + views, count + 1)
            total += views

    if not total:
        return None
    complete = channel_total and total >= channel_total * 0.9
    caveat = None if complete else (
        f"Covers {total:,} of {channel_total:,} lifetime channel views — the rest sits "
        "in videos beyond the pages read, so shares are of what was measured."
    )
    return _summarise("YouTube", "views", grouped, total, len(video_ids),
                      bool(complete), caveat, artist)


async def lastfm_concentration(artist: str, client: httpx.AsyncClient) -> Concentration | None:
    key = os.getenv("LASTFM_API_KEY")
    if not key:
        return None
    response = await client.get(LASTFM, params={
        "method": "artist.getTopTracks", "artist": artist, "api_key": key,
        "format": "json", "limit": 50, "autocorrect": 1})
    if response.status_code != 200:
        return None
    tracks = (response.json().get("toptracks") or {}).get("track", [])

    grouped: dict[str, tuple[str, int, int]] = {}
    total = 0
    for track in tracks:
        plays = int(track.get("playcount") or 0)
        if not plays:
            continue
        slug = canonical(track["name"], artist)
        label, running, count = grouped.get(slug, (track["name"], 0, 0))
        grouped[slug] = (label, running + plays, count + 1)
        total += plays

    if not total:
        return None
    return _summarise(
        "Last.fm", "scrobbles", grouped, total, len(tracks), False,
        "Shares are of this artist's top tracks on Last.fm, whose users are a small "
        "and unrepresentative sample of any market.", artist,
    )


def variants_note(concentrations: list[Concentration]) -> str | None:
    merged = sum(w.variants - 1 for c in concentrations for w in c.works if w.variants > 1)
    if not merged:
        return None
    return (
        f"{merged} duplicate listing(s) were merged into the song they are a version of. "
        "Counted separately, a lead single's share reads lower than it is."
    )
