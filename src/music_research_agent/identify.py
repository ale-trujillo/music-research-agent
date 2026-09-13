"""Recognise an artist from a pasted profile URL.

A pasted link is the highest-quality input this system can receive. Searching a
name means ranking candidates and living with the chance of resolving to the
wrong person -- the failure this project works hardest to prevent. A URL carries
the platform's own identifier, so there is nothing to disambiguate.

Accepts what people actually paste: full URLs, bare handles, app URIs, links
with tracking parameters, and the odd country segment platforms insert.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SPOTIFY_ID = r"[A-Za-z0-9]{22}"

PATTERNS: list[tuple[str, str, str]] = [
    # (platform, kind, regex) -- first capture group is the identifier
    ("spotify", "artist", rf"open\.spotify\.com/(?:intl-[a-z]{{2}}/)?artist/({SPOTIFY_ID})"),
    ("spotify", "artist", rf"spotify:artist:({SPOTIFY_ID})"),
    ("deezer", "artist", r"deezer\.com/(?:[a-z]{2}/)?artist/(\d+)"),
    ("youtube", "channel", r"youtube\.com/channel/(UC[A-Za-z0-9_-]{22})"),
    ("youtube", "handle", r"youtube\.com/@([A-Za-z0-9._-]+)"),
    ("youtube", "handle", r"youtube\.com/c/([A-Za-z0-9._-]+)"),
    ("youtube", "handle", r"youtube\.com/user/([A-Za-z0-9._-]+)"),
    ("apple", "artist", r"music\.apple\.com/(?:[a-z]{2}/)?artist/[^/]+/(\d+)"),
    ("lastfm", "name", r"last\.fm/music/([^/?#]+)"),
    ("musicbrainz", "artist", r"musicbrainz\.org/artist/([0-9a-f-]{36})"),
]


@dataclass(frozen=True)
class PlatformRef:
    platform: str
    kind: str
    id: str
    source_url: str

    def describe(self) -> str:
        return f"{self.platform} {self.kind} {self.id}"


def parse_reference(text: str) -> PlatformRef | None:
    """Pull a platform identifier out of pasted text, or return None.

    Returns None for an ordinary artist name, which is the signal to fall back
    to search. Tracking parameters and surrounding text are ignored rather than
    rejected -- people paste what their share button gave them.
    """
    candidate = text.strip().strip("<>\"'")
    for platform, kind, pattern in PATTERNS:
        if match := re.search(pattern, candidate, re.IGNORECASE):
            value = match.group(1)
            if platform == "lastfm":
                value = value.replace("+", " ")
            return PlatformRef(platform, kind, value, candidate)
    return None


def looks_like_url(text: str) -> bool:
    """A link we could not parse is a different problem from a name."""
    return bool(re.match(r"https?://|www\.|[a-z]+:[a-z]+:", text.strip(), re.IGNORECASE))
