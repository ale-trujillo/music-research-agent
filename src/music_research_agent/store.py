"""Saved artists, and the time series that saving creates.

Favorites are the seed set. Saving an artist feeds them back into discovery, so
each round of use widens the pool -- the list is the flywheel, not a bookmark
folder.

Saving also does something the reports cannot do on their own. Every public
source here returns a point-in-time figure: followers now, listeners now. There
is no growth history anywhere in the free tier, which is why every report says
momentum describes release cadence rather than audience movement. But a
favorite records its figures each time it is saved, so the second save produces
the first trend line this system has ever had.

Storage sits behind an interface because the file is a stand-in. A deployed
service has no durable filesystem, and swapping in a key-value store should not
reach into anything above this module.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .evidence import EvidenceBundle

TRACKED_METRICS = (
    "deezer.fans", "lastfm.listeners", "lastfm.playcount",
    "youtube.subscribers", "youtube.total_views", "deezer.release_count",
)


class Reading(BaseModel):
    """What the platforms said at one moment."""

    at: datetime
    metrics: dict[str, int] = Field(default_factory=dict)


class Favorite(BaseModel):
    name: str
    deezer_id: str | None = None
    spotify_id: str | None = None
    note: str | None = None
    added_at: datetime
    readings: list[Reading] = Field(default_factory=list)

    @property
    def key(self) -> str:
        return self.deezer_id or self.spotify_id or self.name.casefold()

    def latest(self) -> dict[str, int]:
        return self.readings[-1].metrics if self.readings else {}

    def movement(self) -> dict[str, tuple[int, int, float]]:
        """Change between the first and last reading: (from, to, percent).

        Only meaningful once an artist has been saved twice, which is the point
        -- a single save is a snapshot, a second one is a trend.
        """
        if len(self.readings) < 2:
            return {}
        first, last = self.readings[0].metrics, self.readings[-1].metrics
        out: dict[str, tuple[int, int, float]] = {}
        for metric, then in first.items():
            now = last.get(metric)
            if now is None or not then:
                continue
            out[metric] = (then, now, round((now - then) / then * 100, 1))
        return out

    def days_tracked(self) -> int:
        if len(self.readings) < 2:
            return 0
        return (self.readings[-1].at - self.readings[0].at).days


class FavoriteStore(ABC):
    """The seam. A deployed service swaps this for a key-value store."""

    @abstractmethod
    def load(self) -> list[Favorite]: ...

    @abstractmethod
    def save_all(self, favorites: list[Favorite]) -> None: ...

    def add(self, bundle: EvidenceBundle, note: str | None = None) -> Favorite:
        """Save an artist, recording what the platforms say right now."""
        identity = bundle.identity
        reading = Reading(
            at=datetime.now(UTC),
            metrics={
                item.key: item.value for item in bundle.items
                if item.key in TRACKED_METRICS and isinstance(item.value, int)
            },
        )
        favorites = self.load()
        existing = next(
            (f for f in favorites
             if (identity.deezer_id and f.deezer_id == identity.deezer_id)
             or f.name.casefold() == identity.resolved_name.casefold()),
            None,
        )
        if existing:
            # Re-saving is how a trend accumulates, so never overwrite history.
            existing.readings.append(reading)
            if note:
                existing.note = note
            self.save_all(favorites)
            return existing

        favorite = Favorite(
            name=identity.resolved_name, deezer_id=identity.deezer_id,
            spotify_id=identity.spotify_id, note=note,
            added_at=datetime.now(UTC), readings=[reading],
        )
        favorites.append(favorite)
        self.save_all(favorites)
        return favorite

    def remove(self, query: str) -> bool:
        favorites = self.load()
        kept = [f for f in favorites
                if query.casefold() not in f.name.casefold() and f.key != query]
        if len(kept) == len(favorites):
            return False
        self.save_all(kept)
        return True

    def seeds(self) -> list[str]:
        """Favorites as discovery seeds — the flywheel in one line."""
        return [f.deezer_id and f"https://www.deezer.com/artist/{f.deezer_id}" or f.name
                for f in self.load()]


class JsonFileStore(FavoriteStore):
    """Local file. Fine for one person; replaced by a KV store once deployed."""

    def __init__(self, path: Path | None = None):
        self.path = path or Path("favorites.json")

    def load(self) -> list[Favorite]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text())
        return [Favorite.model_validate(item) for item in raw]

    def save_all(self, favorites: list[Favorite]) -> None:
        self.path.write_text(
            json.dumps([f.model_dump(mode="json") for f in favorites], indent=2, ensure_ascii=False)
        )


class RedisStore(FavoriteStore):
    """Favorites in Upstash Redis, over its REST API.

    A deployed function has no durable filesystem, so the JSON file cannot
    follow. REST rather than a Redis client on purpose: a serverless invocation
    cannot hold a connection open between requests, and an HTTP call needs no
    pool to manage or tear down.

    Everything lives under one key. A favorites list is small, read whole on
    every view, and written rarely — splitting it across keys would buy nothing
    and cost a round trip per artist.
    """

    KEY = "favorites"

    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

    def load(self) -> list[Favorite]:
        import httpx

        response = httpx.get(f"{self.url}/get/{self.KEY}", headers=self.headers, timeout=10)
        response.raise_for_status()
        raw = response.json().get("result")
        if not raw:
            return []
        return [Favorite.model_validate(item) for item in json.loads(raw)]

    def save_all(self, favorites: list[Favorite]) -> None:
        import httpx

        payload = json.dumps([f.model_dump(mode="json") for f in favorites], ensure_ascii=False)
        response = httpx.post(
            f"{self.url}/set/{self.KEY}", headers=self.headers, content=payload, timeout=10
        )
        response.raise_for_status()


def _writable(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / ".write-probe"
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False


def open_store() -> FavoriteStore:
    """Redis when a deployment provides it, a file otherwise.

    Both Vercel's KV integration and a direct Upstash project are accepted,
    since they set different names for the same service.

    Without either, a deployed instance still has to run: the working directory
    is read-only there, so the file falls back to /tmp. Those favorites last
    only as long as the instance does, which is why the persistence warning
    below exists — a saved artist quietly disappearing is worse than one that
    never saved.
    """
    url = os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL")
    token = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if url and token:
        return RedisStore(url, token)

    path = Path(os.getenv("FAVORITES_PATH", "favorites.json"))
    if not _writable(path):
        path = Path("/tmp/favorites.json")
    return JsonFileStore(path)


def storage_is_durable() -> bool:
    """False when favorites will not survive the instance."""
    return bool(
        (os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL"))
        and (os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN"))
    ) or not os.getenv("VERCEL")
