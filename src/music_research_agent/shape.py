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

HEAVY_SKEW = 10    # one platform this far ahead is a shape, not noise
LOYAL_PLAYS = 8.0  # plays per listener that indicates return listening

# The platforms that carry most streaming in this market and publish no public
# audience figures. Naming them is not a footnote: the streaming side of every
# comparison below rests on Deezer and Last.fm, both marginal in Colombia, so a
# "video-led" shape can mean the audience is on video -- or merely that video is
# the side we can measure. An earlier version of this classifier called three of
# four test artists "DSP-unconverted", which was a statement about our blind
# spot wearing the costume of a finding.
UNOBSERVED = ("Spotify", "Apple Music")
BLIND_SPOT = (
    "Spotify and Apple Music carry most streaming in this market and expose no "
    "public audience figures. The streaming side here is Deezer and Last.fm, both "
    "minor in Colombia, so a video-led shape may describe what is measurable "
    "rather than where the audience is. Treat it as a question to put to the "
    "artist, not a conclusion."
)


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
            # Deliberately not "unconverted". We cannot see the platform where
            # conversion would show up, so the gap is a question, not a verdict.
            profile = "video-led among measured platforms"
            notes.append(
                f"YouTube shows {yt_subs / dsp:.0f}x the audience visible on the "
                "streaming platforms we can read. Whether that is a conversion "
                f"gap or a measurement gap depends on {' and '.join(UNOBSERVED)}, "
                "which are unobserved here."
            )
        elif dsp > yt_subs * HEAVY_SKEW:
            profile = "audience sits on streaming, not video"
            notes.append(
                "Even the minor streaming platforms outweigh video, which makes "
                "this the one shape the blind spot cannot be producing."
            )
        else:
            profile = "comparable on video and measured streaming"
    elif dsp and not yt_subs:
        profile = "measured on streaming only — no verified YouTube channel"
        notes.append("Catalogue is distributed, but no artist-run YouTube channel was verified.")

    if views and dsp:
        notes.append(
            f"{views:,} lifetime views against {dsp:,} followers and listeners on "
            "measurable platforms. The traffic-source and geography breakdown is "
            "what separates real demand from paid or incidental views, and it is "
            "not public."
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
        evidence_basis=(
            f"headline figures from {', '.join(sorted(covered)) or 'no platform'}; "
            f"{' and '.join(UNOBSERVED)} unobserved"
        ),
        caveats=[WHY_NO_TOTAL, BLIND_SPOT],
        signals=signals, ratios=ratios, profile=profile, notes=notes,
        unobserved=list(UNOBSERVED),
    )
