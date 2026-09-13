"""Everything the pipeline collects before any analysis happens.

The EvidenceBundle is the only thing the LLM is ever allowed to see. It cannot
recall a follower count from training data, because it never gets to answer
from anywhere except this object. The anti-hallucination validator later checks
the finished report against `grounded_numbers()`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from .schema import Citation, Confidence, Identity


# HTTP clients put the full request URL in their error text, query string
# included -- which is how an API key ends up written into a report that gets
# committed or shared. Anything that reaches a report is scrubbed first.
SECRET_PARAM = re.compile(
    r"([?&](?:key|api_?key|access_?token|token|secret|password)=)[^&\s]+",
    re.IGNORECASE,
)
LONG_TOKEN = re.compile(r"\b(?:AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})")
MAX_REASON = 200


def scrub(text: str) -> str:
    """Strip credentials out of anything headed for the report."""
    text = SECRET_PARAM.sub(r"\1REDACTED", text)
    text = LONG_TOKEN.sub("REDACTED", text)
    return text


class Evidence(BaseModel):
    """One fact, with proof of where it came from."""

    key: str = Field(description="Canonical name, e.g. 'spotify.followers'")
    value: Any
    unit: str | None = None
    confidence: Confidence
    citation: Citation

    def as_prompt_line(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        src = self.citation.url or self.citation.source
        return f"- {self.key}: {self.value}{unit}  [{src}]"


class SourceFailure(BaseModel):
    source: str
    reason: str
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EvidenceBundle(BaseModel):
    artist_query: str
    identity: Identity | None = None
    items: list[Evidence] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)
    sources_failed: list[SourceFailure] = Field(default_factory=list)
    raw: dict[str, Any] = Field(
        default_factory=dict,
        description="Untouched payloads, for the qualitative deep-dive agent",
    )

    def add(self, *evidence: Evidence) -> None:
        for item in evidence:
            self.items.append(item)
            if item.citation.source not in self.sources_used:
                self.sources_used.append(item.citation.source)

    def fail(self, source: str, reason: str) -> None:
        """Record a source that returned nothing -- and make it citable.

        A source failing is a fact about the artist's file, not a gap in it.
        Without a key to point at, the model had no way to support "Spotify
        returned no data" and the statement rendered as unsupported inference,
        which is precisely backwards: it is one of the better-established facts
        in the report. Failed sources do not count toward `sources_used`.
        """
        reason = scrub(reason)[:MAX_REASON]
        self.sources_failed.append(SourceFailure(source=source, reason=reason))
        self.items.append(Evidence(
            key=f"source_status.{source}",
            value=f"returned no data ({reason})",
            confidence=Confidence.ABSENT,
            citation=Citation(
                source=source, url=None, retrieved_at=datetime.now(UTC),
                note="source queried and returned nothing",
            ),
        ))

    def get(self, key: str) -> Evidence | None:
        return next((i for i in self.items if i.key == key), None)

    def grounded_numbers(self) -> set[str]:
        """Every figure a source actually returned.

        The validator rejects any number in the finished report that is not in
        this set. Formatted variants are included so "12,345" and "12345" both
        match. Numbers embedded in text values count too -- a release date, a
        track title, an HTTP status inside a failure message. If a figure is
        visible in the evidence, quoting it is sourced, and flagging it would
        cost the validator the precision that makes it worth reading.
        """
        out: set[str] = set()
        for item in self.items:
            if isinstance(item.value, bool):
                continue
            if isinstance(item.value, int | float):
                out.add(str(item.value))
                if isinstance(item.value, int):
                    out.add(f"{item.value:,}")
                else:
                    out.add(f"{item.value:,.2f}".rstrip("0").rstrip("."))
            elif isinstance(item.value, str):
                out.update(re.findall(r"\d[\d,]*\.?\d*", item.value))
        return out

    def for_prompt(self) -> str:
        """The exact text the analysis layer receives. Nothing else."""
        if not self.items:
            return "(no evidence collected)"
        by_source: dict[str, list[Evidence]] = {}
        for item in self.items:
            by_source.setdefault(item.citation.source, []).append(item)

        blocks = []
        for source, items in by_source.items():
            lines = "\n".join(i.as_prompt_line() for i in items)
            blocks.append(f"## {source}\n{lines}")
        if self.sources_failed:
            failed = ", ".join(f"{f.source} ({f.reason})" for f in self.sources_failed)
            blocks.append(f"## sources that returned nothing\n{failed}")
        return "\n\n".join(blocks)

    def absent_sources(self) -> list[str]:
        return [f.source for f in self.sources_failed]

    def coverage_score(self, expected_sources: int) -> float:
        if expected_sources <= 0:
            return 0.0
        return round(len(self.sources_used) / expected_sources, 2)
