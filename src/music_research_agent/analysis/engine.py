"""Stage 3: turn the evidence bundle into the report's analysed sections.

Two properties matter here.

The model sees the evidence and nothing else. There is no artist name in the
system prompt beyond what the bundle carries, no invitation to recall anything,
and no way to emit a citation it did not receive.

The bundle is identical across all six sections, so it sits in the cached
prefix: one cache write, five reads at roughly a tenth of the cost.
"""

from __future__ import annotations

import anthropic

from ..evidence import EvidenceBundle
from .drafts import (
    ArSummaryDraft,
    ComparablesDraft,
    MarketsDraft,
    PositioningDraft,
    RecentActivityDraft,
    SignalsDraft,
)

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

SYSTEM = """You are a music research analyst preparing A&R screening reports on \
emerging Colombian artists.

The evidence below is everything you know about this artist. You have no other \
knowledge of them. If you believe you recognise the artist, disregard it: that \
recollection is not evidence and may be about someone else entirely.

Rules:
- Never state a number that does not appear in the evidence.
- Cite by listing the exact evidence keys that support a statement.
- A statement with no supporting key is inference. Say so plainly in the text.
- Absence of data is a finding. An artist with releases but no audience signal \
is a different prospect from one with both; say which you are looking at.
- These are small artists. Do not inflate. A few hundred listeners is a few \
hundred listeners, and saying so is more useful than flattery.
- Write for an A&R reader deciding whether to take a meeting. Be concrete.

EVIDENCE
========
{evidence}"""

# Descriptive work needs less deliberation than synthesis, so effort is spent
# where judgement actually compounds.
SECTIONS: dict[str, tuple[type, str, str]] = {
    "positioning": (
        PositioningDraft, "medium",
        "Describe how this artist is positioned: genre, sonic character, the scene "
        "or movement they sit in, the story they tell, who listens, and what "
        "distinguishes them from similar acts.",
    ),
    "comparables": (
        ComparablesDraft, "high",
        "Identify comparable artists in two separate groups. tier_peers: artists at "
        "a similar audience size, useful for benchmarking. trajectory_analogs: "
        "artists who once stood roughly where this one stands now, and what "
        "followed for them. Similarity scores in the evidence are unreliable at "
        "this audience size -- a perfect match often means shared listeners rather "
        "than shared sound. Treat them as candidates and say what corroborates each "
        "one. Reject any candidate whose audience is orders of magnitude larger; "
        "that is a recommendation artifact, not a peer.",
    ),
    "markets": (
        MarketsDraft, "medium",
        "Assess markets in two layers. colombia_traction: where inside Colombia "
        "there is evidence of an audience. expansion_path: which markets the "
        "evidence suggests they could grow into. No free source exposes listeners "
        "by country, so everything here is a proxy -- name the proxy in "
        "evidence_type and put the limits in caveats.",
    ),
    "recent_activity": (
        RecentActivityDraft, "low",
        "List what this artist has done in the last twelve months, most recent "
        "first: releases, collaborations, and anything else the evidence shows. "
        "For each, say why it matters. Dates must come from the evidence.",
    ),
    "signals": (
        SignalsDraft, "high",
        "Assess momentum: accelerating, steady, cooling, or insufficient_data. "
        "Then give green flags and risks. Risks are the questions an A&R should "
        "ask before signing -- be specific and unflattering where the evidence "
        "warrants it.",
    ),
    "ar_summary": (
        ArSummaryDraft, "high",
        "Write five to eight bullets for an A&R committee: the thesis on this "
        "artist, what would make them worth a meeting, and what would not. Lead "
        "with the most decision-relevant point.",
    ),
}


class AnalysisEngine:
    def __init__(self, bundle: EvidenceBundle):
        self.bundle = bundle
        self.client = anthropic.Anthropic()
        self.cost_usd = 0.0
        self.cache_reads = 0

    def _system(self) -> list[dict]:
        return [{
            "type": "text",
            "text": SYSTEM.format(evidence=self.bundle.for_prompt()),
            # Same evidence for every section: cache it once, read it five times.
            "cache_control": {"type": "ephemeral"},
        }]

    def run(self, section: str):
        model_cls, effort, instruction = SECTIONS[section]
        response = self.client.messages.parse(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=self._system(),
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=[{"role": "user", "content": instruction}],
            output_format=model_cls,
        )
        self._track(response.usage)
        return response.parsed_output

    def _track(self, usage) -> None:
        # Opus 5: $5 / $25 per MTok; cache writes ~1.25x input, reads ~0.1x.
        write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        read = getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_reads += read
        self.cost_usd += (
            usage.input_tokens * 5 / 1_000_000
            + write * 6.25 / 1_000_000
            + read * 0.5 / 1_000_000
            + usage.output_tokens * 25 / 1_000_000
        )
