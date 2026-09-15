"""Song titles arrive dirty, and both cleaning them and grouping them matter.

Grouping decides the headline figure. A lead single is listed many times over --
lyric video, official video, live, collaboration credit -- and counted separately
one artist's top song read 43% of plays where grouped it is 70%. The naive
reading understates concentration exactly where concentration is the measurement.

Cleaning decides whether the label is readable. Every case below is a real title
from the acceptance set.
"""

import pytest

from music_research_agent.catalogue import canonical, clean_title


@pytest.mark.parametrize("raw,artist,expected", [
    ("Ela Taubert, Morat - ¿Cómo Pasó? (Lyric Video)", "Ela Taubert", "¿Cómo Pasó?"),
    ("Susana Cala - Domingo (Acústico)", "Susana Cala", "Domingo"),
    ("GAMALL - LA CHIMBA", "Gamall", "LA CHIMBA"),
    # No space before the dash — real, and it defeated a stricter separator.
    ("Ela Taubert- TE PROMETO (El Fin De Una Era)", "Ela Taubert",
     "TE PROMETO (El Fin De Una Era)"),
    # Reversed: song first, artist after. Prefix-stripping alone left "OYE MAMI - Gamall".
    ("OYE MAMI  - Gamall x Legend Effect | VISUALIZER", "Gamall", "OYE MAMI"),
    ("Andrea Prieto, Arevalo - POR SI VUELVO A VERTE", "Andrea Prieto",
     "POR SI VUELVO A VERTE"),
    ("Casita En La Playa", "Gamall", "Casita En La Playa"),
])
def test_label_shows_the_song(raw, artist, expected):
    assert clean_title(raw, artist) == expected


def test_a_parenthetical_that_is_part_of_the_title_survives():
    """'(El Fin De Una Era)' is the title; '(Acústico)' is a version of it."""
    assert "El Fin De Una Era" in clean_title(
        "Ela Taubert- TE PROMETO (El Fin De Una Era)", "Ela Taubert")
    assert clean_title("Susana Cala - Domingo (Acústico)", "Susana Cala") == "Domingo"


def test_hyphenated_words_are_not_split():
    assert clean_title("Hip-Hop Anthem", "Gamall") == "Hip-Hop Anthem"


def test_versions_of_one_song_group_together():
    """The three listings that turned a 43% share into 70%."""
    slugs = {
        canonical(t, "Ela Taubert") for t in (
            "¿Cómo Pasó?",
            "¿Cómo Pasó? - Con Joe Jonas",
            "¿Cómo Pasó? Con Joe Jonas",
            "Ela Taubert, Morat - ¿Cómo Pasó? (Lyric Video)",
        )
    }
    assert len(slugs) == 1


def test_different_songs_stay_apart():
    assert canonical("¿Para Qué?", "Ela Taubert") != canonical("¿Por Qué?", "Ela Taubert")
