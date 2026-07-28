"""Tests for the MAESTRO eval CLI helpers.

``load_midi_notes`` is verified by round-tripping a MIDI written with the same
``pretty_midi`` it reads back with. ``load_maestro_pairs`` is exercised against
a fake MAESTRO directory (index csv + a MIDI file) using a stub transcriber, so
no dataset or basic-pitch is required.
"""

from __future__ import annotations

import csv

import pytest

pretty_midi = pytest.importorskip("pretty_midi")

from cli.run_eval import load_maestro_pairs, load_midi_notes
from piano_transcribe.types import NoteEvent


def _write_midi(path, notes):
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    for pitch, start, end in notes:
        inst.notes.append(
            pretty_midi.Note(velocity=90, pitch=pitch, start=start, end=end)
        )
    pm.instruments.append(inst)
    pm.write(str(path))


def test_load_midi_notes_roundtrip(tmp_path):
    midi_path = tmp_path / "x.midi"
    _write_midi(midi_path, [(60, 0.0, 0.5), (64, 0.5, 1.0), (67, 1.0, 2.0)])

    notes = load_midi_notes(midi_path)
    assert [n.pitch for n in notes] == [60, 64, 67]
    assert notes[0].onset_s == pytest.approx(0.0, abs=1e-3)
    assert notes[2].offset_s == pytest.approx(2.0, abs=1e-3)
    assert all(isinstance(n, NoteEvent) for n in notes)


def test_load_maestro_pairs_with_stub_transcriber(tmp_path):
    # Fake MAESTRO layout: an index csv + one midi + a dummy audio file.
    midi_rel = "piece1.midi"
    audio_rel = "piece1.wav"
    _write_midi(tmp_path / midi_rel, [(60, 0.0, 0.5), (62, 0.5, 1.0)])
    (tmp_path / audio_rel).write_bytes(b"RIFF....")  # never actually decoded

    with (tmp_path / "maestro-v3.0.0.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["audio_filename", "midi_filename"])
        writer.writeheader()
        writer.writerow({"audio_filename": audio_rel, "midi_filename": midi_rel})

    class StubTranscriber:
        def transcribe(self, path):
            return [NoteEvent(60, 0.0, 0.5, 80)]  # one correct, one missed

    pairs = load_maestro_pairs(tmp_path, limit=5, transcriber=StubTranscriber())
    assert len(pairs) == 1
    name, reference, estimate = pairs[0]
    assert name == "piece1"
    assert [n.pitch for n in reference] == [60, 62]
    assert [n.pitch for n in estimate] == [60]
