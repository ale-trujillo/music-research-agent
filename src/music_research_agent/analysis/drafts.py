"""What the model is allowed to return.

The model never writes a citation. It returns `evidence_keys` -- references to
keys that already exist in the bundle -- and the assembler resolves those to
real citations. Inventing a source is therefore not something the model can do
badly; it is something it cannot express.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..schema import Confidence


class ClaimDraft(BaseModel):
    text: str
    confidence: Confidence
    evidence_keys: list[str] = Field(
        description="Keys from the evidence block that support this. Empty means "
        "the statement is inference, and it will be labelled as such."
    )


class PositioningDraft(BaseModel):
    genre_primary: str | None
    genre_secondary: list[str]
    sonic_descriptors: list[str]
    scene: str | None
    narrative: ClaimDraft | None
    audience_profile: ClaimDraft | None
    differentiation: ClaimDraft | None
    confidence: Confidence
    evidence_basis: str
    caveats: list[str]


class ComparableDraft(BaseModel):
    artist: str
    why: str
    shared_signals: list[str]
    confidence: Confidence
    evidence_keys: list[str]


class TrajectoryAnalogDraft(ComparableDraft):
    stage_matched: str
    what_happened_next: str


class ComparablesDraft(BaseModel):
    tier_peers: list[ComparableDraft]
    trajectory_analogs: list[TrajectoryAnalogDraft]
    confidence: Confidence
    evidence_basis: str
    caveats: list[str]


class MarketSignalDraft(BaseModel):
    market: str
    strength: Confidence
    evidence_type: str
    evidence_keys: list[str]


class MarketsDraft(BaseModel):
    colombia_traction: list[MarketSignalDraft]
    expansion_path: list[MarketSignalDraft]
    touring_footprint: list[str]
    confidence: Confidence
    evidence_basis: str
    caveats: list[str]


class ActivityEventDraft(BaseModel):
    date: str | None
    type: str
    title: str
    significance: str
    evidence_keys: list[str]


class RecentActivityDraft(BaseModel):
    events: list[ActivityEventDraft]
    confidence: Confidence
    evidence_basis: str
    caveats: list[str]


class SignalsDraft(BaseModel):
    momentum: str
    momentum_rationale: ClaimDraft | None
    green_flags: list[ClaimDraft]
    risks: list[ClaimDraft]
    confidence: Confidence
    evidence_basis: str
    caveats: list[str]


class ArSummaryDraft(BaseModel):
    bullets: list[ClaimDraft]
