"""Quantized, voiced, spelled notes -> music21 Score -> MusicXML.

Piano is notated on a two-staff grand staff; every other instrument gets a
single staff with its own clef (see :mod:`piano_transcribe.instruments`). Note
names are expected to already be in *written* pitch (the pipeline applies any
transposition before spelling), so this module just places them.

Chords: notes that land on the same metrical position within a staff are merged
into a single ``chord.Chord`` (this is what makes left-hand block chords read as
chords instead of a pile of overlapping noteheads). Within a staff the result is
one voice — each attack's duration is clipped to the next attack so nothing
overlaps — which keeps homophonic music (melody + block-chord accompaniment)
clean. Independent overlapping voices within one hand are the remaining, harder
case; see the module TODO.
"""

from __future__ import annotations

import math
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

from .instruments import Instrument, get_instrument, music21_clef_name
from .spelling import KeyEstimate
from .types import BeatGrid, QuantizedNote


def _place_notes(part, entries) -> float:
    """Insert ``entries`` into ``part`` as chords/notes; return the end offset.

    ``entries`` is a list of ``(onset, duration, name, pitch)`` where ``onset``
    and ``duration`` are ``Fraction`` beats, ``name`` a music21 note name (or
    ``None`` to fall back to ``pitch``). Notes sharing an onset become one chord;
    each attack is clipped to the next onset so voices never overlap.
    """
    from music21 import chord as m21chord
    from music21 import note as m21note

    by_onset: dict[Fraction, list] = defaultdict(list)
    for onset, duration, name, pitch in entries:
        by_onset[onset].append((duration, name, pitch))

    onsets = sorted(by_onset)
    end = 0.0
    for i, onset in enumerate(onsets):
        group = by_onset[onset]

        # De-duplicate identical pitches at the same onset.
        seen: set[int] = set()
        members = []
        for duration, name, pitch in group:
            if pitch in seen:
                continue
            seen.add(pitch)
            members.append((duration, name, pitch))

        # A chord sustains as long as its longest member; clip to the next
        # attack on this staff so single-voice notation stays overlap-free.
        dur = max(d for d, _, _ in members)
        if i + 1 < len(onsets):
            gap = onsets[i + 1] - onset
            if dur > gap:
                dur = gap
        ql = float(dur)
        if ql <= 0:
            continue

        if len(members) == 1:
            _, name, pitch = members[0]
            element = m21note.Note(name) if name else m21note.Note(pitch)
        else:
            element = m21chord.Chord([name if name else pitch for _, name, pitch in members])
        element.quarterLength = ql
        part.insert(float(onset), element)
        end = max(end, float(onset) + ql)

    return end


def _finalize_part(part, end_ql, full_ql) -> None:
    """Fill interior gaps + trailing space with rests, then bar into measures."""
    from music21 import note as m21note

    if end_ql < full_ql - 1e-9:
        rest = m21note.Rest()
        rest.quarterLength = full_ql - end_ql
        part.insert(end_ql, rest)
    part.makeRests(fillGaps=True, inPlace=True, hideRests=False)
    part.makeMeasures(inPlace=True)


def build_score(
    notes: list[QuantizedNote],
    grid: BeatGrid,
    key: KeyEstimate,
    note_names: list[str] | None = None,
    instrument: Instrument | str | None = None,
    title: str = "Untitled",
):  # -> music21.stream.Score
    """Assemble a ``music21.stream.Score`` for ``instrument``.

    Args:
        notes: Quantized notes; for a grand staff they carry ``staff`` (1/2).
        grid: Beat grid, for the time signature and bar length.
        key: Estimated key, for the key signature.
        note_names: Per-note *written* spellings aligned to ``notes`` (falls
            back to the MIDI number when a name is ``None``).
        instrument: An :class:`Instrument`, its key string, or ``None`` (piano).
        title: Score title metadata.
    """
    from music21 import clef as m21clef
    from music21 import key as m21key
    from music21 import layout, metadata, meter, stream, tempo as m21tempo

    inst = instrument if isinstance(instrument, Instrument) else get_instrument(instrument)
    if note_names is None:
        note_names = [None] * len(notes)

    ks_sharps = key.key_signature_sharps
    time_sig = grid.time_signature
    bar_ql = grid.beats_per_bar * (4.0 / grid.beat_unit)
    total_ql = max(
        (float(q.onset_beats) + float(q.duration_beats) for q in notes), default=0.0
    )
    bars = max(1, math.ceil(total_ql / bar_ql - 1e-9))
    full_ql = bars * bar_ql

    def new_part(part_id, clef_name):
        part = (
            stream.PartStaff(id=part_id)
            if inst.notation == "grand"
            else stream.Part(id=part_id)
        )
        part.partName = ""
        part.partAbbreviation = ""
        part.insert(0, getattr(m21clef, clef_name)())
        part.insert(0, m21key.KeySignature(ks_sharps))
        part.insert(0, meter.TimeSignature(time_sig))
        return part

    # Collect (onset, duration, name, pitch) entries, split by staff.
    staff_entries: dict[int, list] = {1: [], 2: []}
    for qnote, name in zip(notes, note_names):
        staff = qnote.staff if qnote.staff in (1, 2) else 1
        staff_entries[staff].append(
            (qnote.onset_beats, qnote.duration_beats, name, qnote.event.pitch)
        )

    score = stream.Score()
    md = metadata.Metadata()
    md.title = title
    score.insert(0, md)

    def mark_tempo(part) -> None:
        """Put the performed tempo in ``part``'s first measure.

        Without a tempo mark music21 exports MIDI at its default 120 BPM, so the
        score plays back at the wrong speed and any follow-along cursor drifts
        out of sync with the audio.

        It has to go *inside* a measure. A ``MetronomeMark`` inserted on the
        Score is silently dropped by the MusicXML writer once the parts are
        already measured — which they are here, since ``_finalize_part`` bars
        them itself — so the exported file carried no tempo at all and opened at
        120 BPM in every other notation program.
        """
        bpm = grid.tempo_bpm
        if not bpm:
            return
        mark = m21tempo.MetronomeMark(number=round(bpm, 2))
        first = part.getElementsByClass(stream.Measure).first()
        (first or part).insert(0.0, mark)

    if inst.notation == "grand":
        treble = new_part("RH", "TrebleClef")
        bass = new_part("LH", "BassClef")
        _finalize_part(treble, _place_notes(treble, staff_entries[1]), full_ql)
        _finalize_part(bass, _place_notes(bass, staff_entries[2]), full_ql)
        mark_tempo(treble)
        score.insert(0, treble)
        score.insert(0, bass)
        score.insert(0, layout.StaffGroup(
            [treble, bass], name=inst.display_name, symbol="brace", barTogether=True))
    else:
        part = new_part("P1", music21_clef_name(inst.clef))
        all_entries = staff_entries[1] + staff_entries[2]
        _finalize_part(part, _place_notes(part, all_entries), full_ql)
        mark_tempo(part)
        part.partName = inst.display_name
        score.insert(0, part)

    return score


def export_musicxml(score, out_path: str | Path) -> Path:
    """Write a music21 Score to a ``.musicxml`` file and return the path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    score.write("musicxml", fp=str(out_path))
    return out_path
