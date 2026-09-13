"""Everything the pipeline collects before any analysis happens.

The EvidenceBundle is the only thing the LLM is ever allowed to see. It cannot
recall a follower count from training data, because it never gets to answer
from anywhere except this object. The anti-hallucination validator later checks
the finished report against `grounded_numbers()`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from .schema import Citation, Confidence, Identity


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
        self.sources_failed.append(SourceFailure(source=source, reason=reason))

    def get(self, key: str) -> Evidence | None:
        return next((i for i in self.items if i.key == key), None)

    def grounded_numbers(self) -> set[str]:
        """Every numeric value that actually came from a source.

        The validator rejects any figure in the finished report that is not in
        this set. Formatted variants are included so that "12,345" and "12345"
        both match what the source returned.
        """
        out: set[str] = set()
        for item in self.items:
            if isinstance(item.value, bool) or not isinstance(item.value, int | float):
                continue
            out.add(str(item.value))
            if isinstance(item.value, int):
                out.add(f"{item.value:,}")
            else:
                out.add(f"{item.value:,.2f}".rstrip("0").rstrip("."))
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

    def coverage_score(self, expected_sources: int) -> float:
        if expected_sources <= 0:
            return 0.0
        return round(len(self.sources_used) / expected_sources, 2)
