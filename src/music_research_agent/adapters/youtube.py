"""YouTube. The richest traction signal here, and the weakest identity guarantee.

Spotify and Deezer join on stable IDs. YouTube offers only a display name, and
on the golden set that gap was nearly catastrophic: a short artist name matched
a channel with 235,000 subscribers and 86 million views run by an unrelated
producer in another country, while the actual artist had roughly 24
subscribers.

What makes verification possible is the auto-generated "<Artist> - Topic"
channel, which YouTube builds from the distributor's catalog. Its video titles
are the artist's actual tracks, so overlapping them with releases already in
the bundle proves the channel belongs to this artist. No overlap and no country
match means we report nothing rather than guess.
"""

from __future__ import annotations

import os
import re

import httpx

from ..evidence import Evidence, EvidenceBundle
from ..schema import Confidence, Identity
from .base import CorroboratingAdapter

SEARCH = "https://www.googleapis.com/youtube/v3/search"
CHANNELS = "https://www.googleapis.com/youtube/v3/channels"
PLAYLIST_ITEMS = "https://www.googleapis.com/youtube/v3/playlistItems"
EXPECTED_COUNTRY = "CO"

# Quota arithmetic decides the design here. search.list costs 100 units against
# a 10,000/day allowance; playlistItems.list costs 1. Listing a channel's
# uploads playlist instead of searching it takes a run from ~900 units to ~105,
# which is the difference between 11 artists a day and 95.
SEARCH_COST = 100
CHANNEL_LIST_PART = "snippet,statistics,contentDetails"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


class YouTubeAdapter(CorroboratingAdapter):
    name = "youtube"
    requires_env = ("YOUTUBE_API_KEY",)
    timeout = 30.0

    async def fetch_corroborated(
        self, identity: Identity, client: httpx.AsyncClient, bundle: EvidenceBundle
    ) -> list[Evidence]:
        key = os.getenv("YOUTUBE_API_KEY")
        known = self._known_titles(bundle)

        r = await client.get(SEARCH, params={
            "key": key, "q": identity.resolved_name, "type": "channel",
            "part": "snippet", "maxResults": 8,
        })
        r.raise_for_status()
        ids = [i["snippet"]["channelId"] for i in r.json().get("items", [])]
        if not ids:
            return []

        detail = await client.get(CHANNELS, params={
            "key": key, "id": ",".join(ids), "part": CHANNEL_LIST_PART,
        })
        detail.raise_for_status()

        # The two channel kinds answer different questions. A "- Topic" channel
        # is generated from the distributor's catalog, so matching titles there
        # prove identity -- but nobody subscribes to it, so its counts say
        # nothing about reach. The artist's own channel carries the real
        # traction and has to earn trust separately.
        topic: tuple[int, dict, list[str]] | None = None
        main: tuple[int, dict, list[str]] | None = None

        for ch in detail.json().get("items", []):
            snippet = ch["snippet"]
            title = snippet["title"]
            if _norm(identity.resolved_name) not in _norm(title):
                continue
            titles = await self._recent_titles(ch, client, key)
            matched = [t for t in titles if _norm(t) in known or any(k in _norm(t) for k in known)]
            in_country = snippet.get("country") == EXPECTED_COUNTRY
            score = len(matched) * 10 + (3 if in_country else 0)
            if not score:
                continue
            slot = "topic" if title.rstrip().lower().endswith("- topic") else "main"
            current = topic if slot == "topic" else main
            if current is None or score > current[0]:
                if slot == "topic":
                    topic = (score, ch, matched)
                else:
                    main = (score, ch, matched)

        if topic is None and main is None:
            return []

        out: list[Evidence] = []
        if topic is not None:
            _, ch, matched = topic
            out.append(Evidence(
                key="youtube.catalog_confirmed", value=ch["snippet"]["title"],
                confidence=Confidence.HIGH,
                citation=self.cite(
                    f"https://www.youtube.com/channel/{ch['id']}",
                    f"auto-generated catalog channel; titles match known releases: {', '.join(matched[:3])}",
                ),
            ))

        if main is None:
            # Catalog presence without a verified artist channel is itself an
            # A&R signal: distributed, but not building an audience on YouTube.
            out.append(Evidence(
                key="youtube.artist_channel", value=None,
                confidence=Confidence.ABSENT,
                citation=self.cite(None, "no artist-run channel could be verified against releases or country"),
            ))
            return out

        score, ch, matched = main
        snippet = ch["snippet"]
        stats = ch.get("statistics", {})
        url = f"https://www.youtube.com/channel/{ch['id']}"
        conf = Confidence.HIGH if matched else Confidence.MEDIUM
        note = (f"verified against known releases: {', '.join(matched[:3])}" if matched
                else f"matched on name and country={EXPECTED_COUNTRY} only, not on releases")

        out.append(Evidence(
            key="youtube.artist_channel", value=snippet["title"],
            confidence=conf, citation=self.cite(url, note),
        ))
        for field, label, unit in (
            ("subscriberCount", "subscribers", "subscribers"),
            ("viewCount", "total_views", "views"),
            ("videoCount", "video_count", "videos"),
        ):
            if (raw := stats.get(field)) is not None:
                out.append(Evidence(
                    key=f"youtube.{label}", value=int(raw), unit=unit,
                    confidence=conf, citation=self.cite(url, note),
                ))
        return out

    # Any source that can name a release feeds the corroboration. Reading only
    # specific sources here once cost this adapter its accuracy: when Spotify
    # left the fan-out, the known set silently shrank from thirteen titles to
    # five, the artist's real channel matched none of them, and a channel with
    # 105 subscribers won on a country match over one with 138,000.
    TITLE_KEYS = ("deezer.top_track", "deezer.recent_release", "spotify.recent_release")

    def _known_titles(self, bundle: EvidenceBundle) -> set[str]:
        """Every release or track name any source has established."""
        known: set[str] = set()
        for item in bundle.items:
            if not isinstance(item.value, str):
                continue
            if not item.key.startswith(self.TITLE_KEYS):
                continue
            # Dated entries are stored as "2026-07-24 — Suegra (single)".
            value = item.value.split("—", 1)[1].rsplit("(", 1)[0] if "—" in item.value else item.value
            known.add(_norm(value))
        return {k for k in known if len(k) > 3}

    async def _recent_titles(self, channel: dict, client: httpx.AsyncClient, key: str) -> list[str]:
        """Recent uploads, via the playlist rather than search.

        Every channel has an auto-maintained uploads playlist. Reading it costs
        one quota unit; searching the same channel costs a hundred.
        """
        uploads = (
            channel.get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads")
        )
        if not uploads:
            return []
        r = await client.get(PLAYLIST_ITEMS, params={
            "key": key, "playlistId": uploads, "part": "snippet", "maxResults": 15,
        })
        if r.status_code != 200:
            return []
        return [i["snippet"]["title"] for i in r.json().get("items", [])]
