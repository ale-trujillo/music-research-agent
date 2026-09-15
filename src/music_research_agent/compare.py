"""Compare saved artists without pretending they are on one scale.

Two artists are never measured the same way. One has a verified YouTube channel
and the other does not; one sits on Deezer and the other barely registers there.
Printing two columns of numbers invites a reader to subtract them, and the
subtraction is usually meaningless -- a follow is not a play, and an artist we
could not measure on a platform is not an artist absent from it.

So a comparison here states the unit on every row, names who leads each axis
without declaring an overall winner, and says plainly when the two are not
comparable on a given measure. The ratios matter more than the totals: they are
the only figures that survive a difference in scale.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .shape import MEASURES
from .store import Favorite

# Ratios are scale-free, so they are the only honest way to line up a
# 300-follower artist against one with 300,000.
DERIVED = {
    "plays per listener": ("lastfm.playcount", "lastfm.listeners"),
    "views per subscriber": ("youtube.total_views", "youtube.subscribers"),
    "followers per release": ("deezer.fans", "deezer.release_count"),
}


class Row(BaseModel):
    metric: str
    unit: str
    measures: str
    values: dict[str, float | None] = Field(
        description="Artist name to value. None means not measurable, not zero."
    )
    leader: str | None = None
    comparable: bool = True
    note: str | None = None


class Trend(BaseModel):
    artist: str
    metric: str
    first: int
    last: int
    percent: float
    days: int


class Comparison(BaseModel):
    artists: list[str]
    absolute: list[Row]
    ratios: list[Row]
    trends: list[Trend] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _leader(values: dict[str, float | None]) -> tuple[str | None, bool]:
    """Who leads, and whether the row is a fair comparison at all."""
    present = {k: v for k, v in values.items() if v is not None}
    if len(present) < len(values):
        # One artist unmeasured on this platform. Naming a leader would read as
        # "beats them" when it means "we could only see one of them".
        return (max(present, key=present.get) if present else None), False
    if not present:
        return None, False
    return max(present, key=present.get), True


def compare(favorites: list[Favorite]) -> Comparison:
    names = [f.name for f in favorites]
    latest = {f.name: f.latest() for f in favorites}

    absolute: list[Row] = []
    for metric, (platform, unit, measures) in MEASURES.items():
        values: dict[str, float | None] = {
            name: latest[name].get(metric) for name in names
        }
        if all(v is None for v in values.values()):
            continue
        leader, comparable = _leader(values)
        missing = [n for n, v in values.items() if v is None]
        absolute.append(Row(
            metric=f"{platform} {unit}", unit=unit, measures=measures,
            values=values, leader=leader, comparable=comparable,
            note=(f"not measurable for {', '.join(missing)} — absent here means "
                  "unmeasured, not zero") if missing else None,
        ))

    ratios: list[Row] = []
    for label, (numerator, denominator) in DERIVED.items():
        values = {}
        for name in names:
            num, den = latest[name].get(numerator), latest[name].get(denominator)
            values[name] = round(num / den, 1) if num and den else None
        if all(v is None for v in values.values()):
            continue
        leader, comparable = _leader(values)
        ratios.append(Row(
            metric=label, unit="ratio",
            measures="scale-free, so it survives a difference in size",
            values=values, leader=leader, comparable=comparable,
        ))

    trends = [
        Trend(artist=f.name, metric=metric, first=before, last=after,
              percent=percent, days=f.days_tracked())
        for f in favorites
        for metric, (before, after, percent) in f.movement().items()
        if percent
    ]

    notes: list[str] = []
    untracked = [f.name for f in favorites if len(f.readings) < 2]
    if untracked:
        notes.append(
            f"No trend yet for {', '.join(untracked)} — saved once. Movement needs "
            "a second save; public sources carry no history to backfill from."
        )
    incomparable = [r.metric for r in absolute if not r.comparable]
    if incomparable:
        notes.append(
            f"Not a like-for-like comparison on: {', '.join(incomparable)}. "
            "One artist could not be measured there."
        )
    notes.append(
        "No overall ranking is given. These columns measure different things on "
        "different platforms, and the artists are not on the same scale — the "
        "ratios are the rows that survive that."
    )
    return Comparison(artists=names, absolute=absolute, ratios=ratios,
                      trends=trends, notes=notes)
