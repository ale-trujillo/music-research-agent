"""A source we could not reach is not an artist with nothing to show.

This distinction has been got wrong twice in this codebase -- once in the
Spotify adapter, where a 429 was recorded as "no data for this artist", and
once in triage, where a failed request scored identically to a dormant artist
and moved one candidate between 0 and 8 releases on consecutive runs. Both are
silent: the number looks reasonable and says the wrong thing.
"""

from music_research_agent.discover import Candidate
from music_research_agent.evidence import EvidenceBundle, scrub
from music_research_agent.triage import Triaged, _score


def test_unreachable_source_outranks_a_genuinely_dormant_artist():
    unreachable = _score(Triaged(name="source down", deezer_id="1", score=0, fans=500,
                                 listeners=9000, releases_12mo=None,
                                 plays_per_listener=24.0, corroboration=3))
    dormant = _score(Triaged(name="dormant", deezer_id="2", score=0, fans=500,
                             listeners=9000, releases_12mo=0,
                             plays_per_listener=24.0, corroboration=3))
    assert unreachable.score > dormant.score
    assert "?rel/12mo" in unreachable.line()


def test_failed_source_becomes_citable_evidence():
    """Otherwise 'Spotify returned no data' renders as unsupported inference."""
    bundle = EvidenceBundle(artist_query="t")
    bundle.fail("spotify", "rate limited (HTTP 429)")
    assert any(item.key == "source_status.spotify" for item in bundle.items)
    assert bundle.sources_used == [], "a failure must not count toward coverage"


def test_credentials_never_reach_a_report():
    """HTTP clients put the full request URL in error text, query string included."""
    leaked = "Client error for url 'https://api.test/v3?key=AIzaSyC0000000000000000000&q=x'"
    assert "AIzaSy" not in scrub(leaked)
    assert "REDACTED" in scrub(leaked)


def test_corroboration_counts_distinct_seeds_and_graphs():
    """One algorithm's guess is weaker than two agreeing."""
    single = Candidate(name="a", found_via=["seed1"], sources=["lastfm"])
    both = Candidate(name="b", found_via=["seed1", "seed2"], sources=["lastfm", "deezer"])
    assert both.corroboration > single.corroboration
