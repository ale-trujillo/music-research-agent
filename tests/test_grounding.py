"""The report must not contain a figure no source returned.

This is the project's first acceptance criterion, and the validator that
enforces it failed twice in ways worth keeping tests around: it flagged
twenty-four date fragments on its first real run, and it flagged an HTTP status
quoted verbatim from a failure message. A validator nobody trusts protects
nothing, so precision is tested as carefully as detection.
"""

from datetime import UTC, datetime

import pytest

from music_research_agent.assemble import Assembler
from music_research_agent.evidence import Evidence, EvidenceBundle
from music_research_agent.schema import Citation, Confidence, Identity


def bundle_with(**metrics) -> EvidenceBundle:
    bundle = EvidenceBundle(
        artist_query="test",
        identity=Identity(resolved_name="Test", disambiguation_confidence=Confidence.HIGH),
    )
    bundle.add(*[
        Evidence(key=key, value=value, confidence=Confidence.HIGH,
                 citation=Citation(source="deezer", url="https://example.test",
                                   retrieved_at=datetime.now(UTC)))
        for key, value in metrics.items()
    ])
    return bundle


@pytest.fixture
def assembler() -> Assembler:
    return Assembler(bundle_with(**{"deezer.fans": 11800, "lastfm.listeners": 409}))


def test_flags_a_figure_no_source_returned(assembler):
    assembler.check_numbers("Roughly 45000 monthly listeners on Spotify", "where")
    assert assembler.ungrounded, "an invented audience figure must be caught"


def test_accepts_a_figure_a_source_returned(assembler):
    assembler.check_numbers("The channel reports 11,800 subscribers", "where")
    assert not assembler.ungrounded


@pytest.mark.parametrize("text", [
    "released 2026-07-24, the artist's most recent",       # dates were split into 07 and 24
    "#2 on Deezer top tracks and the 3rd single",          # ordinals
    "five releases in the last 12 months",                 # small counts in prose
    "the album 'Arial 12' anchors the catalogue",          # numbered release titles
])
def test_does_not_flag_ordinary_prose(assembler, text):
    """Twenty-four false positives on one report is how a validator gets ignored."""
    assembler.check_numbers(text, "where")
    assert not assembler.ungrounded, f"false positive on: {text}"


def test_numbers_inside_text_evidence_count_as_sourced():
    """An HTTP status quoted from a failure message is sourced, not fabricated."""
    bundle = EvidenceBundle(artist_query="t")
    bundle.fail("youtube", "Client error '429 Too Many Requests'")
    assert "429" in bundle.grounded_numbers()


def test_a_claim_citing_nothing_is_demoted_to_inference(assembler):
    from music_research_agent.analysis.drafts import ClaimDraft

    claim = assembler.claim(
        ClaimDraft(text="The artist is poised for a breakout.",
                   confidence=Confidence.HIGH, evidence_keys=[]),
        "where",
    )
    assert claim.confidence is Confidence.LOW
    assert not claim.citations
