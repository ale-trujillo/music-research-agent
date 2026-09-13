"""Stage 3: turn the evidence bundle into the report's analysed sections.

Two properties matter here.

The model sees the evidence and nothing else. There is no artist name in the
system prompt beyond what the bundle carries, no invitation to recall anything,
and no way to emit a citation it did not receive.

The bundle is identical across all six sections, which looks like an obvious
case for prompt caching -- but measurement says otherwise. The output schema is
rendered ahead of the system prompt in the cached prefix, so each section's
distinct schema invalidates it. Varying `effort` does not; the schema does.
Caching here would only pay the 1.25x write premium on a prefix nothing ever
reads, so it is deliberately absent.
"""

from __future__ import annotations

import asyncio

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

A source that was queried and returned nothing appears as `source_status.<name>`. Cite it like any other evidence. A missing platform is an established fact about this artist's file, not a guess.

Length discipline. This is a screening document -- it has to be readable in two minutes or it will not be read at all:
- One idea per bullet, under 45 words. No preamble, no restating the question.
- At most 5 green flags, 5 risks, 4 caveats per section. Choose the strongest; a long list of near-duplicates reads as padding and buries what matters.
- Never repeat a point you have already made in this section.

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


# Sequential, the six sections take close to four minutes. They share one input
# and never read each other, so fanning them out costs nothing in quality.
FIRST_SECTION = "positioning"


class AnalysisEngine:
    def __init__(self, bundle: EvidenceBundle):
        self.bundle = bundle
        self.client = anthropic.AsyncAnthropic()
        self.cost_usd = 0.0
        self.cache_reads = 0
        # Per-section usage. Reconstructing spend from the finished report does
        # not work -- the assembler expands evidence keys into full citations,
        # so the report is far larger than anything the model wrote. Record it
        # at the call site or do not claim to know it.
        self.usage_log: list[dict] = []

    def _system(self) -> list[dict]:
        # No cache_control: see the module docstring. Re-measure with
        # usage.cache_read_input_tokens before adding it back.
        return [{"type": "text", "text": SYSTEM.format(evidence=self.bundle.for_prompt())}]

    async def run(self, section: str):
        model_cls, effort, instruction = SECTIONS[section]
        response = await self.client.messages.parse(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=self._system(),
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=[{"role": "user", "content": instruction}],
            output_format=model_cls,
        )
        self._track(response.usage, section, effort)
        if response.stop_reason == "max_tokens":
            # Otherwise this surfaces as an opaque "invalid JSON" from the
            # parser, which sends you hunting for a schema bug that isn't there.
            raise RuntimeError(
                f"section '{section}' hit max_tokens ({MAX_TOKENS}) and returned "
                "truncated JSON; raise MAX_TOKENS"
            )
        return response.parsed_output

    async def run_all(self) -> dict:
        """All six at once. Total time becomes the slowest section, not the sum."""
        names = list(SECTIONS)
        results = await asyncio.gather(*(self.run(s) for s in names))
        return dict(zip(names, results, strict=True))

    def _track(self, usage, section: str = "", effort: str = "") -> None:
        # Opus 5: $5 / $25 per MTok; cache writes ~1.25x input, reads ~0.1x.
        write = getattr(usage, "cache_creation_input_tokens", 0) or 0  # expected 0
        read = getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_reads += read
        cost = (
            usage.input_tokens * 5 / 1_000_000
            + write * 6.25 / 1_000_000
            + read * 0.5 / 1_000_000
            + usage.output_tokens * 25 / 1_000_000
        )
        self.cost_usd += cost
        self.usage_log.append({
            "section": section, "effort": effort,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": round(cost, 5),
        })
