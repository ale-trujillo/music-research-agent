"""Stage 4: turn drafts into the report, resolving every reference to a source.

This is where the anti-hallucination rule is enforced rather than requested.
The model returned evidence keys; each one is looked up in the bundle. A key
that does not resolve is dropped and recorded in `data_quality.ungrounded_claims`,
so a claim that cited nothing real cannot pass silently into the report.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from .analysis.drafts import ClaimDraft
from .evidence import EvidenceBundle
from .schema import (
    ActivityEvent,
    ArtistReport,
    Citation,
    Claim,
    Comparable,
    Comparables,
    Confidence,
    DataQuality,
    MarketSignal,
    Markets,
    Metric,
    Positioning,
    RecentActivity,
    Signals,
    Snapshot,
    TrajectoryAnalog,
)

NUMBER = re.compile(r"\b\d[\d,]*\.?\d*\b")
# Ordinary prose numbers that are not claims about the artist's scale.
ALLOWED_BARE = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"}


class Assembler:
    def __init__(self, bundle: EvidenceBundle):
        self.bundle = bundle
        self.by_key = {i.key: i for i in bundle.items}
        self.grounded = bundle.grounded_numbers()
        self.ungrounded: list[str] = []

    def citations(self, keys: list[str]) -> list[Citation]:
        out = []
        for key in keys:
            if (item := self.by_key.get(key)) is not None:
                out.append(item.citation)
        return out

    def check_numbers(self, text: str, where: str) -> None:
        """Every figure in prose must trace to something a source returned."""
        for raw in NUMBER.findall(text):
            cleaned = raw.rstrip(".")
            if cleaned in ALLOWED_BARE or cleaned in self.grounded:
                continue
            if cleaned.replace(",", "") in self.grounded:
                continue
            if re.fullmatch(r"(19|20)\d\d", cleaned):  # years appear in dates
                continue
            self.ungrounded.append(f"{where}: '{cleaned}' in “{text[:70]}…”")

    def claim(self, draft: ClaimDraft | None, where: str) -> Claim | None:
        if draft is None:
            return None
        self.check_numbers(draft.text, where)
        cites = self.citations(draft.evidence_keys)
        if draft.evidence_keys and not cites:
            self.ungrounded.append(f"{where}: cited keys resolve to nothing")
        return Claim(
            text=draft.text,
            # A claim that cites nothing is inference, whatever the model called it.
            confidence=draft.confidence if cites else Confidence.LOW,
            citations=cites,
        )

    def build(self, drafts: dict, run_id: str, duration_s: float, cost_usd: float) -> ArtistReport:
        pos, cmp_, mkt = drafts["positioning"], drafts["comparables"], drafts["markets"]
        act, sig, summ = drafts["recent_activity"], drafts["signals"], drafts["ar_summary"]

        snapshot = Snapshot(
            confidence=Confidence.HIGH if self.bundle.items else Confidence.ABSENT,
            evidence_basis=f"{len(self.bundle.items)} data points from "
                           f"{', '.join(self.bundle.sources_used) or 'no source'}",
            metrics=[
                Metric(name=i.key, value=i.value, unit=i.unit,
                       confidence=i.confidence, citation=i.citation)
                for i in self.bundle.items
                if isinstance(i.value, int | float) and not isinstance(i.value, bool)
            ],
        )

        positioning = Positioning(
            confidence=pos.confidence, evidence_basis=pos.evidence_basis, caveats=pos.caveats,
            genre_primary=pos.genre_primary, genre_secondary=pos.genre_secondary,
            sonic_descriptors=pos.sonic_descriptors, scene=pos.scene,
            narrative=self.claim(pos.narrative, "positioning.narrative"),
            audience_profile=self.claim(pos.audience_profile, "positioning.audience"),
            differentiation=self.claim(pos.differentiation, "positioning.differentiation"),
        )

        comparables = Comparables(
            confidence=cmp_.confidence, evidence_basis=cmp_.evidence_basis, caveats=cmp_.caveats,
            tier_peers=[
                Comparable(artist=c.artist, why=c.why, shared_signals=c.shared_signals,
                           confidence=c.confidence, citations=self.citations(c.evidence_keys))
                for c in cmp_.tier_peers
            ],
            trajectory_analogs=[
                TrajectoryAnalog(artist=c.artist, why=c.why, shared_signals=c.shared_signals,
                                 confidence=c.confidence, citations=self.citations(c.evidence_keys),
                                 stage_matched=c.stage_matched, what_happened_next=c.what_happened_next)
                for c in cmp_.trajectory_analogs
            ],
        )

        markets = Markets(
            confidence=mkt.confidence, evidence_basis=mkt.evidence_basis, caveats=mkt.caveats,
            touring_footprint=mkt.touring_footprint,
            colombia_traction=[
                MarketSignal(market=m.market, strength=m.strength, evidence_type=m.evidence_type,
                             citations=self.citations(m.evidence_keys))
                for m in mkt.colombia_traction
            ],
            expansion_path=[
                MarketSignal(market=m.market, strength=m.strength, evidence_type=m.evidence_type,
                             citations=self.citations(m.evidence_keys))
                for m in mkt.expansion_path
            ],
        )

        events = []
        for e in act.events:
            self.check_numbers(e.significance, f"activity.{e.title[:20]}")
            cites = self.citations(e.evidence_keys)
            events.append(ActivityEvent(
                date=_parse_date(e.date), type=e.type, title=e.title,
                significance=e.significance, citation=cites[0] if cites else None,
            ))
        recent = RecentActivity(
            confidence=act.confidence, evidence_basis=act.evidence_basis,
            caveats=act.caveats, events=events,
        )

        signals = Signals(
            confidence=sig.confidence, evidence_basis=sig.evidence_basis, caveats=sig.caveats,
            momentum=sig.momentum,
            momentum_rationale=self.claim(sig.momentum_rationale, "signals.momentum"),
            green_flags=[c for c in (self.claim(f, "signals.green_flag") for f in sig.green_flags) if c],
            risks=[c for c in (self.claim(r, "signals.risk") for r in sig.risks) if c],
        )

        ar_summary = [c for c in (self.claim(b, "ar_summary") for b in summ.bullets) if c]

        absent = [name for name, sec in (
            ("positioning", positioning), ("comparables", comparables), ("markets", markets),
            ("recent_activity", recent), ("signals", signals),
        ) if sec.confidence == Confidence.ABSENT]

        return ArtistReport(
            generated_at=datetime.now(UTC), run_id=run_id,
            duration_s=round(duration_s, 1), cost_usd=round(cost_usd, 4),
            identity=self.bundle.identity,
            snapshot=snapshot, positioning=positioning, comparables=comparables,
            markets=markets, recent_activity=recent, signals=signals,
            ar_summary=ar_summary,
            data_quality=DataQuality(
                coverage_score=self.bundle.coverage_score(4),
                sources_used=self.bundle.sources_used,
                sources_failed=[f"{f.source}: {f.reason}" for f in self.bundle.sources_failed],
                fields_absent=absent,
                caveats=sorted({c for s in (positioning, comparables, markets, recent, signals)
                                for c in s.caveats}),
                ungrounded_claims=self.ungrounded,
            ),
        )


def _parse_date(raw: str | None):
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(raw[: len(fmt.replace("%Y", "2026"))], fmt).date()
        except ValueError:
            continue
    return None
