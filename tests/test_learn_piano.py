"""Tests for scales, fingering, and the learn endpoints."""

from __future__ import annotations

import pytest

from piano_transcribe import learn


# --- scale spelling ----------------------------------------------------------

@pytest.mark.parametrize("tonic,expected", [
    (0,  ["C", "D", "E", "F", "G", "A", "B", "C"]),
    (7,  ["G", "A", "B", "C", "D", "E", "F#", "G"]),
    (10, ["B♭", "C", "D", "E♭", "F", "G", "A", "B♭"]),
    # F# major's seventh is E#, not F — a scale uses each letter exactly once.
    (6,  ["F#", "G#", "A#", "B", "C#", "D#", "E#", "F#"]),
])
def test_major_scales_are_spelled_correctly(tonic, expected):
    assert learn.scale(tonic, "major")["note_names"] == expected


def test_every_major_scale_uses_each_letter_once():
    """The defining property of a diatonic scale."""
    for tonic in range(12):
        names = learn.scale(tonic, "major")["note_names"][:7]
        letters = [n[0] for n in names]
        assert sorted(letters) == list("ABCDEFG"), f"tonic {tonic}: {names}"


def test_harmonic_minor_raises_the_seventh():
    names = learn.scale(9, "harmonic_minor")["note_names"]
    assert names == ["A", "B", "C", "D", "E", "F", "G#", "A"]


def test_minor_scales_use_flat_spelling_where_conventional():
    assert learn.scale(0, "natural_minor")["note_names"] == [
        "C", "D", "E♭", "F", "G", "A♭", "B♭", "C"
    ]


def test_scale_pitches_match_the_interval_pattern():
    s = learn.scale(0, "major")
    assert s["pitches"] == [60, 62, 64, 65, 67, 69, 71, 72]


def test_unknown_scale_type_raises():
    with pytest.raises(ValueError):
        learn.scale(0, "not-a-scale")


# --- fingering ---------------------------------------------------------------

def test_c_major_fingering_is_the_standard_one():
    f = learn.scale(0, "major")["fingering"]
    assert f["right"] == [1, 2, 3, 1, 2, 3, 4, 5]
    assert f["left"] == [5, 4, 3, 2, 1, 3, 2, 1]


def test_fingering_covers_the_octave():
    for tonic in (0, 2, 4, 5, 7, 9, 11):
        f = learn.scale(tonic, "major")["fingering"]
        assert f is not None
        assert len(f["right"]) == 8 and len(f["left"]) == 8
        assert all(1 <= x <= 5 for x in f["right"] + f["left"])


def test_no_fingering_invented_for_scales_without_a_standard_one():
    """A wrong fingering would be worse than none."""
    assert learn.scale(0, "blues")["fingering"] is None
    assert learn.scale(0, "pentatonic_major")["fingering"] is None


def test_scale_types_listed():
    keys = {t["key"] for t in learn.list_scale_types()}
    assert {"major", "natural_minor", "harmonic_minor", "blues"} <= keys


def test_practice_steps_present():
    assert len(learn.PRACTICE_STEPS) >= 5
    assert all(len(t) == 2 for t in learn.PRACTICE_STEPS)


# --- learn endpoints ---------------------------------------------------------

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main.db, "DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setattr(main.db, "DATA_DIR", tmp_path)
    with TestClient(main.app) as c:
        yield c


def test_learn_endpoints(client):
    assert client.get("/learn/scales?tonic=7&type=major").json()["note_names"][0] == "G"
    assert client.get("/learn/scales?type=bogus").status_code == 400
    assert len(client.get("/learn/scale-types").json()["types"]) >= 5
    assert len(client.get("/learn/practice").json()["steps"]) >= 5
