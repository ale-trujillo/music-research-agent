"""Audience shape: the cross-platform picture, without inventing a total.

There is no public number for "total plays across platforms", and the figures
we collect cannot be added into one. A Deezer fan is a follow, a Last.fm
listener is a person inside a small and unrepresentative sample, a YouTube view
is a video impression that may not be music at all. Summing them produces a
figure with no referent, which is exactly the kind of claim this project exists
to prevent.

What replaces it is more useful anyway. An artist with ten million views and
twenty-nine followers has a conversion problem; an artist with twenty-two plays
per listener has a catalogue that holds people. A single total would erase both
of those readings. So the platforms are shown side by side with their units
stated, the ratios are computed and labelled as derived, and the shape is named.

Everything here is arithmetic over cited figures, computed in code. Asking a
model to do it would reintroduce the exact risk the validator exists to catch.
"""

from __future__ import annotations

from .evidence import EvidenceBundle
from .schema import AudienceRatio, AudienceShape, AudienceSignal, Confidence

# What each platform's headline number actually counts. The unit is the whole
# point: these columns are not the same measurement wearing different names.
MEASURES: dict[str, tuple[str, str, str]] = {
    "deezer.fans": ("Deezer", "follows", "people who saved the artist, not plays"),
    "lastfm.listeners": ("Last.fm", "listeners", "distinct Last.fm users only — a small, non-representative sample"),
    "lastfm.playcount": ("Last.fm", "plays", "scrobbles from Last.fm users only"),
    "youtube.subscribers": ("YouTube", "subscribers", "channel follows"),
    "youtube.total_views": ("YouTube", "views", "lifetime video views, undated, music and non-music alike"),
    "youtube.video_count": ("YouTube", "videos", "uploads on the artist channel"),
    "deezer.release_count": ("Deezer", "releases", "catalogue size"),
}

WHY_NO_TOTAL = (
    "No total is given because these figures measure different things — follows, "
    "sampled listeners, scrobbles and video views — and adding them would produce "
    "a number with no referent. Real cross-platform stream totals exist only in "
    "the artist's own distributor reporting or in licensed industry data."
)

HEAVY_SKEW = 10       # one platform this far ahead is a shape, not noise
LOYAL_PLAYS = 8.0     # plays per listener that indicates return listening
THIN_CONVERSION = 50  # views per DSP follower above this is a conversion gap


def build_shape(bundle: EvidenceBundle) -> AudienceShape:
    by_key = {i.key: i for i in bundle.items}

    signals: list[AudienceSignal] = []
    for key, (platform, unit, measures) in MEASURES.items():
        item = by_key.get(key)
        if item is None or not isinstance(item.value, int):
            continue
        signals.append(AudienceSignal(
            platform=platform, metric=key, value=item.value, unit=unit,
            measures=measures, citation=item.citation,
        ))

    def val(key: str) -> int | None:
        item = by_key.get(key)
        return item.value if item and isinstance(item.value, int) else None

    ratios: list[AudienceRatio] = []

    def ratio(name: str, num_key: str, den_key: str, reads_as) -> float | None:
        num, den = val(num_key), val(den_key)
        if not num or not den:
            return None
        computed = round(num / den, 1)
        ratios.append(AudienceRatio(
            name=name, value=computed,
            derived_from=[num_key, den_key],
            reads_as=reads_as(computed),
            citations=[by_key[num_key].citation, by_key[den_key].citation],
        ))
        return computed

    plays_per_listener = ratio(
        "plays per Last.fm listener", "lastfm.playcount", "lastfm.listeners",
        lambda v: ("returns to the catalogue rather than sampling it once"
                   if v >= LOYAL_PLAYS else "listens shallow — sampled more than replayed"),
    )
    ratio("views per video", "youtube.total_views", "youtube.video_count",
          lambda v: f"averages {v:,.0f} views an upload; says nothing about spread across them")
    ratio("Deezer follows per release", "deezer.fans", "deezer.release_count",
          lambda v: ("catalogue is converting on Deezer" if v >= 5
                     else "output is far ahead of any Deezer following"))

    yt_subs, dz_fans, lf_listeners = (
        val("youtube.subscribers"), val("deezer.fans"), val("lastfm.listeners")
    )
    dsp = sum(x for x in (dz_fans, lf_listeners) if x)
    views = val("youtube.total_views")

    notes: list[str] = []
    profile = "insufficient data to characterise"
    if yt_subs and dsp:
        if yt_subs > dsp * HEAVY_SKEW:
            profile = "video-led, DSP-unconverted"
            notes.append(
                f"YouTube holds {yt_subs / dsp:.0f}x the audience the streaming "
                "platforms show. The video audience exists; it has not moved to DSPs."
            )
        elif dsp > yt_subs * HEAVY_SKEW:
            profile = "DSP-led, little video presence"
            notes.append("Streaming platforms carry the audience; video is not a channel here.")
        else:
            profile = "balanced across video and streaming"
    elif dsp and not yt_subs:
        profile = "streaming-only — no verified artist channel on YouTube"
        notes.append("Catalogue is distributed, but no artist-run YouTube channel was verified.")

    if views and dsp and views / dsp > THIN_CONVERSION:
        notes.append(
            f"{views:,} lifetime views against {dsp:,} followers and listeners "
            "combined. Ask for the traffic-source and geography breakdown before "
            "reading the view count as demand."
        )
    if plays_per_listener and plays_per_listener >= LOYAL_PLAYS:
        notes.append(
            f"{plays_per_listener} plays per listener: small audience, but it returns."
        )

    covered = {s.platform for s in signals}
    confidence = (
        Confidence.HIGH if len(covered) >= 3
        else Confidence.MEDIUM if len(covered) == 2
        else Confidence.LOW if covered
        else Confidence.ABSENT
    )

    return AudienceShape(
        confidence=confidence,
        evidence_basis=f"headline figures from {', '.join(sorted(covered)) or 'no platform'}",
        caveats=[WHY_NO_TOTAL],
        signals=signals, ratios=ratios, profile=profile, notes=notes,
    )
