"""The output contract. Everything else in this package exists to fill this in.

Two rules drive the shape of these models:

1. Every quantitative claim carries the source it came from. A number without a
   Citation cannot be represented, so the pipeline cannot accidentally emit one.
2. Emerging artists have thin public data. Missing is a first-class state with a
   reason attached -- never a zero, never an LLM estimate.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0.0"


class Confidence(str, Enum):
    """How much weight an A&R reader should put on a value."""

    HIGH = "high"      # straight from an official API
    MEDIUM = "medium"  # derived, aggregated, or from a secondary source
    LOW = "low"        # proxy signal or inference from sparse evidence
    ABSENT = "absent"  # no evidence found -- see `reason`


class MissingReason(str, Enum):
    NOT_PUBLIC = "not_public"            # the API does not expose this at all
    SOURCE_FAILED = "source_failed"      # the source errored or timed out
    NO_DATA_FOR_ARTIST = "no_data"       # source responded, artist not covered
    BELOW_THRESHOLD = "below_threshold"  # too little signal to report honestly


class Citation(BaseModel):
    source: str = Field(description="Adapter that produced this, e.g. 'spotify'")
    url: str | None = Field(default=None, description="Human-verifiable URL")
    retrieved_at: datetime
    note: str | None = None


class Metric(BaseModel):
    """A number that can prove where it came from."""

    name: str
    value: float | int | str | None
    unit: str | None = None
    confidence: Confidence
    citation: Citation | None = None
    missing_reason: MissingReason | None = None

    def is_grounded(self) -> bool:
        """A present value must carry a citation. The validator enforces this."""
        return self.value is None or self.citation is not None


class Claim(BaseModel):
    """A qualitative statement. Marked as interpretation, not measurement."""

    text: str
    confidence: Confidence
    citations: list[Citation] = Field(default_factory=list)


class Section(BaseModel):
    """Base for every analysed section, so confidence is never optional."""

    confidence: Confidence
    evidence_basis: str = Field(
        description="Which sources actually backed this section, in plain English"
    )
    caveats: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------

class Identity(BaseModel):
    """Resolved before anything else. A report on the wrong artist is worse
    than no report, so alternates considered stay visible."""

    resolved_name: str
    spotify_id: str | None = None
    musicbrainz_id: str | None = None
    origin_country: str | None = None
    origin_city: str | None = None
    active_since: int | None = None
    label_status: str | None = None
    disambiguation_confidence: Confidence
    alternates_considered: list[str] = Field(default_factory=list)


class Snapshot(Section):
    """The hard numbers. Sparse by design for emerging artists."""

    metrics: list[Metric] = Field(default_factory=list)


class Positioning(Section):
    genre_primary: str | None = None
    genre_secondary: list[str] = Field(default_factory=list)
    sonic_descriptors: list[str] = Field(default_factory=list)
    scene: str | None = Field(
        default=None,
        description="The movement or collective the artist sits in -- for "
        "emerging Colombian acts this predicts more than any metric",
    )
    narrative: Claim | None = None
    audience_profile: Claim | None = None
    differentiation: Claim | None = None


class Comparable(BaseModel):
    artist: str
    why: str
    shared_signals: list[str] = Field(default_factory=list)
    confidence: Confidence
    citations: list[Citation] = Field(default_factory=list)


class TrajectoryAnalog(Comparable):
    """An artist who stood where this one stands now. Carries the A&R thesis."""

    stage_matched: str
    what_happened_next: str


class Comparables(Section):
    tier_peers: list[Comparable] = Field(default_factory=list)
    trajectory_analogs: list[TrajectoryAnalog] = Field(default_factory=list)


class MarketSignal(BaseModel):
    market: str
    strength: Confidence
    evidence_type: str = Field(
        description="What backs this: shows, press, playlist, streaming proxy"
    )
    citations: list[Citation] = Field(default_factory=list)


class Markets(Section):
    """Two layers: where the artist is today, and where they could go.

    Free APIs do not expose per-country listeners, so everything here is a
    proxy. The caveat travels with the data rather than living in a footnote.
    """

    colombia_traction: list[MarketSignal] = Field(
        default_factory=list, description="City-level: Bogota, Medellin, Cali..."
    )
    expansion_path: list[MarketSignal] = Field(
        default_factory=list, description="Mexico, US Latin, Spain, Southern Cone"
    )
    touring_footprint: list[str] = Field(default_factory=list)


class ActivityEvent(BaseModel):
    date: date | None
    type: str = Field(description="release | show | press | collab | playlist")
    title: str
    significance: str
    citation: Citation | None = None


class RecentActivity(Section):
    """Rolling 12 months, most recent first."""

    events: list[ActivityEvent] = Field(default_factory=list)
    window_months: int = 12


class Signals(Section):
    momentum: str | None = Field(
        default=None, description="accelerating | steady | cooling | insufficient_data"
    )
    momentum_rationale: Claim | None = None
    green_flags: list[Claim] = Field(default_factory=list)
    risks: list[Claim] = Field(
        default_factory=list, description="What an A&R should ask before signing"
    )


class DataQuality(BaseModel):
    """A visible section of the report, not debug metadata.

    An A&R needs to know how solid the floor is before standing on it.
    """

    coverage_score: float = Field(ge=0.0, le=1.0)
    sources_used: list[str] = Field(default_factory=list)
    sources_failed: list[str] = Field(default_factory=list)
    fields_absent: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    ungrounded_claims: list[str] = Field(
        default_factory=list,
        description="Populated by the anti-hallucination validator. Non-empty "
        "means the report shipped with unverified numbers.",
    )


class ArtistReport(BaseModel):
    schema_version: str = SCHEMA_VERSION
    generated_at: datetime
    run_id: str
    duration_s: float | None = None
    cost_usd: float | None = None

    identity: Identity
    snapshot: Snapshot
    positioning: Positioning
    comparables: Comparables
    markets: Markets
    recent_activity: RecentActivity
    signals: Signals
    ar_summary: list[Claim] = Field(
        default_factory=list, description="5-8 bullets: the thesis, for committee"
    )
    data_quality: DataQuality
