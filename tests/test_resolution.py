"""Resolving to the wrong artist is the worst failure this system can have.

A report about the wrong person is worse than no report, and it fails silently:
every figure in it is real, just not theirs. Searching a short artist name
returns the target alongside a globally famous act with roughly 200,000x the
audience, so ranking by popularity produces exactly that.
"""

from music_research_agent.identify import looks_like_url, parse_reference
from music_research_agent.resolve import normalize
from music_research_agent.search import ArtistHit, _rank


def hit(name: str, fans: int) -> ArtistHit:
    return ArtistHit(name=name, deezer_id="1", fans=fans, releases=1)


def test_exact_name_beats_a_far_larger_artist():
    """The Akuo/Akon case: 21 followers must outrank 4.7 million."""
    target, giant = hit("Akuo", 21), hit("Akon", 4_785_185)
    assert _rank(target, "akuo") > _rank(giant, "akuo")


def test_audience_only_breaks_ties_between_equal_matches():
    small, large = hit("Susana Baca", 6_532), hit("Susana Zabaleta", 2_992)
    assert _rank(small, "susana") > _rank(large, "susana")


def test_normalize_ignores_case_and_accents():
    assert normalize("NATALIA NATALIA") == normalize("Natalia Natalia")
    assert normalize("Nabález") == normalize("nabalez")


class TestPastedLinks:
    """A pasted link skips ranking entirely, which is why it is the better input."""

    def test_spotify_with_tracking_parameters(self):
        ref = parse_reference("https://open.spotify.com/artist/68LgpWsaAwjflP3CLXC0LB?si=abc")
        assert (ref.platform, ref.id) == ("spotify", "68LgpWsaAwjflP3CLXC0LB")

    def test_spotify_with_locale_segment(self):
        ref = parse_reference("https://open.spotify.com/intl-es/artist/68LgpWsaAwjflP3CLXC0LB")
        assert ref.id == "68LgpWsaAwjflP3CLXC0LB"

    def test_app_uri(self):
        assert parse_reference("spotify:artist:68LgpWsaAwjflP3CLXC0LB").platform == "spotify"

    def test_deezer_with_country_segment(self):
        ref = parse_reference("https://www.deezer.com/es/artist/127869142")
        assert (ref.platform, ref.id) == ("deezer", "127869142")

    def test_youtube_handle(self):
        ref = parse_reference("https://youtube.com/@susanacala")
        assert (ref.platform, ref.kind, ref.id) == ("youtube", "handle", "susanacala")

    def test_a_plain_name_is_not_a_link(self):
        assert parse_reference("Susana Cala") is None
        assert not looks_like_url("Susana Cala")

    def test_an_unrecognised_link_is_distinguishable_from_a_name(self):
        """So the user gets 'unsupported link', not a search for a URL."""
        assert parse_reference("https://example.com/x") is None
        assert looks_like_url("https://example.com/x")
