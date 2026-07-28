"""Tests for chord construction, identification and key harmony."""

from __future__ import annotations

import pytest

from piano_transcribe import chords


# --- building ----------------------------------------------------------------

@pytest.mark.parametrize("root,quality,expected", [
    (0, "maj", [60, 64, 67]),        # C  E  G
    (0, "min", [60, 63, 67]),        # C  Eb G
    (2, "min7", [62, 65, 69, 72]),   # D  F  A  C
    (7, "7", [67, 71, 74, 77]),      # G  B  D  F
    (0, "dim", [60, 63, 66]),
    (0, "sus4", [60, 65, 67]),
])
def test_build_chord_pitches(root, quality, expected):
    assert chords.build_chord(root, quality).pitches == expected


def test_inversions_lift_the_lowest_note():
    root = chords.build_chord(0, "maj")            # C E G
    first = chords.build_chord(0, "maj", inversion=1)
    second = chords.build_chord(0, "maj", inversion=2)
    assert root.pitches == [60, 64, 67]
    assert first.pitches == [64, 67, 72]           # E G C
    assert second.pitches == [67, 72, 76]          # G C E
    # An inversion is the same chord, so the pitch classes don't change.
    assert {p % 12 for p in first.pitches} == {p % 12 for p in root.pitches}


def test_unknown_quality_raises():
    with pytest.raises(ValueError):
        chords.build_chord(0, "not-a-chord")


# --- identification ----------------------------------------------------------

@pytest.mark.parametrize("pitches,name", [
    ([60, 64, 67], "C"),
    ([60, 63, 67], "Cmin"),
    ([62, 65, 69, 72], "Dmin7"),
    ([67, 71, 74, 77], "G7"),
    ([60, 64, 67, 71], "Cmaj7"),
    ([60, 63, 66, 69], "Cdim7"),
])
def test_identify_named_chords(pitches, name):
    result = chords.identify_chord(pitches)
    assert result["exact"] is True
    assert result["name"] == name


def test_identify_detects_inversion():
    """E-G-C is still C major, but with E in the bass."""
    result = chords.identify_chord([64, 67, 72])
    assert result["exact"] is True
    assert result["root"] == "C"
    assert result["inversion"] == 1
    assert result["name"] == "C/E"


def test_identify_is_octave_agnostic():
    """Spreading a chord across octaves doesn't change what it is."""
    assert chords.identify_chord([48, 64, 79])["name"] == "C"


def test_build_then_identify_roundtrip():
    for root in range(12):
        for quality in ("maj", "min", "min7", "7", "maj7"):
            chord = chords.build_chord(root, quality)
            back = chords.identify_chord(chord.pitches)
            assert back["exact"] is True, (root, quality)
            assert back["root"] == chords.NOTE_NAMES_SHARP[root]


def test_unrecognised_set_still_suggests_something():
    """Experimenting must never hit a dead end."""
    result = chords.identify_chord([60, 61, 66, 71])
    assert result["exact"] is False
    assert result["name"]                 # a suggestion, flagged as approximate
    assert "closest" in result["full_name"]


def test_two_notes_are_named_as_an_interval():
    result = chords.identify_chord([60, 67])
    assert "perfect 5th" in result["full_name"]
    assert result["exact"] is False


def test_empty_selection_is_safe():
    assert chords.identify_chord([])["name"] is None


# --- keys and progressions ---------------------------------------------------

def test_major_diatonic_chords():
    degrees = chords.diatonic_chords(0, "major")
    assert [d["numeral"] for d in degrees] == ["I", "ii", "iii", "IV", "V", "vi", "vii°"]
    assert [d["name"] for d in degrees][:5] == ["C", "Dmin", "Emin", "F", "G"]


def test_minor_diatonic_chords():
    degrees = chords.diatonic_chords(9, "minor")   # A minor
    assert degrees[0]["name"] == "Amin"
    assert [d["numeral"] for d in degrees][:4] == ["i", "ii°", "III", "iv"]


def test_progressions_use_chords_from_the_key():
    progs = chords.progressions(0, "major")
    assert progs, "no major progressions"
    pop = next(p for p in progs if p["name"] == "I–V–vi–IV")
    assert [c["name"] for c in pop["chords"]] == ["C", "G", "Amin", "F"]


def test_minor_progressions_are_not_offered_for_major():
    names = {p["name"] for p in chords.progressions(0, "major")}
    assert "i–iv–v–i" not in names


def test_chord_musicxml_is_engravable():
    xml = chords.chord_musicxml([60, 64, 67], "C")
    assert "score-partwise" in xml
    assert xml.count("<chord") >= 2     # 3-note chord -> 2 chord members
