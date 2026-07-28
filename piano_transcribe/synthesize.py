"""Sheet music -> playable MIDI (with a chosen instrument) + analysis.

The reverse of transcription: read a Score (see :mod:`importscore`), turn it
into note events, export a MIDI whose program matches the chosen instrument (so
a player renders the right timbre), and reuse :mod:`analyze` for the same
summary panel the transcription side shows.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import analyze as analyze_mod
from . import importscore, spelling
from .instruments import get_instrument
from .types import BeatGrid, NoteEvent

# General MIDI program numbers per instrument key (0-indexed).
GM_PROGRAM = {
    "piano": 0,
    "guitar": 24,        # acoustic guitar (nylon)
    "bass_guitar": 33,   # electric bass (finger)
    "violin": 40,
    "viola": 41,
    "cello": 42,
    "flute": 73,
    "clarinet": 71,
    "alto_sax": 65,
    "trumpet": 56,
    "voice": 52,         # choir aahs
}


def _velocity(element) -> int:
    vol = getattr(element, "volume", None)
    v = getattr(vol, "velocity", None) if vol is not None else None
    return int(v) if v else 72


def score_to_events(score) -> list[NoteEvent]:
    """Flatten a music21 Score to ``NoteEvent``s in seconds (chords expanded)."""
    from music21 import chord as m21chord
    from music21 import note as m21note

    flat = score.flatten()
    events: list[NoteEvent] = []
    for entry in flat.secondsMap:
        element = entry["element"]
        onset = float(entry["offsetSeconds"])
        end = onset + float(entry["durationSeconds"])
        if isinstance(element, m21note.Note):
            events.append(NoteEvent(element.pitch.midi, onset, end, _velocity(element)))
        elif isinstance(element, m21chord.Chord):
            vel = _velocity(element)
            for p in element.pitches:
                events.append(NoteEvent(p.midi, onset, end, vel))
    events.sort(key=lambda e: (e.onset_s, e.pitch))
    return events


def _tempo_bpm(score) -> float:
    marks = score.flatten().getElementsByClass("MetronomeMark")
    for mm in marks:
        if mm.number:
            return float(mm.number)
    return 120.0


def _grid(score, duration_s: float) -> BeatGrid:
    bpm = _tempo_bpm(score)
    seconds_per_beat = 60.0 / bpm
    n = max(2, int(duration_s / seconds_per_beat) + 1)
    beats = [i * seconds_per_beat for i in range(n)]
    ts = score.flatten().getElementsByClass("TimeSignature")
    num, den = (ts[0].numerator, ts[0].denominator) if ts else (4, 4)
    return BeatGrid(beat_times_s=beats, downbeats_s=beats[::num],
                    beats_per_bar=num, beat_unit=den)


def export_midi(score, instrument_key: str, out_path: str | Path) -> Path:
    """Write ``score`` to a MIDI file with the instrument's GM program set.

    music21's own instrument handling is inconsistent across parse sources
    (MusicXML vs MIDI), so the program is stamped in a reliable post-step with
    pretty_midi after music21 writes the notes.
    """
    import tempfile

    import pretty_midi

    program = GM_PROGRAM.get(instrument_key, 0)
    tmp = Path(tempfile.mkdtemp()) / "tmp.mid"
    score.write("midi", fp=str(tmp))

    pm = pretty_midi.PrettyMIDI(str(tmp))
    for inst in pm.instruments:
        if not inst.is_drum:
            inst.program = program

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pm.write(str(out_path))
    return out_path


def _set_title(score, title: str | None) -> None:
    """Set the display title (music21 otherwise labels it 'Music21 Fragment')."""
    from music21 import metadata as m21meta

    if score.metadata is None:
        score.insert(0, m21meta.Metadata())
    score.metadata.title = title or ""
    score.metadata.movementName = title or ""


def default_soundfont() -> str | None:
    """Locate a General MIDI soundfont for offline rendering.

    Honours ``$PIANO_SOUNDFONT``; otherwise falls back to the small GM
    soundfont that ships with pretty_midi (TimGM6mb.sf2).
    """
    env = os.environ.get("PIANO_SOUNDFONT")
    if env and Path(env).exists():
        return env
    try:
        import pretty_midi

        bundled = Path(pretty_midi.__file__).parent / "TimGM6mb.sf2"
        if bundled.exists():
            return str(bundled)
    except Exception:  # noqa: BLE001
        pass
    return None


def midi_to_wav(
    midi_path: str | Path,
    wav_path: str | Path,
    soundfont: str | None = None,
    sample_rate: int = 44100,
) -> Path | None:
    """Render a MIDI file to WAV with fluidsynth, for offline playback.

    Returns the WAV path, or ``None`` if fluidsynth or a soundfont isn't
    available (callers fall back to browser-side MIDI playback).
    """
    fluidsynth = shutil.which("fluidsynth")
    sf = soundfont or default_soundfont()
    if not fluidsynth or not sf:
        return None

    wav_path = Path(wav_path)
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [fluidsynth, "-ni", "-F", str(wav_path), "-r", str(sample_rate),
             sf, str(midi_path)],
            check=True, capture_output=True, timeout=180,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    return wav_path if wav_path.exists() else None


def synthesize(
    sheet_path: str | Path,
    out_midi: str | Path,
    out_musicxml: str | Path,
    instrument_key: str = "piano",
    title: str | None = None,
) -> dict:
    """Sheet file -> MIDI + display MusicXML + analysis dict.

    Raises :class:`importscore.ScoreImportError` if the sheet can't be read or
    contains no notes.
    """
    score = importscore.load_score(sheet_path)
    events = score_to_events(score)
    if not events:
        raise importscore.ScoreImportError("No notes were found in the sheet music.")

    duration_s = max(e.offset_s for e in events)
    _set_title(score, title)

    # A clean MusicXML for on-screen rendering (before MIDI mutates instruments).
    out_musicxml = Path(out_musicxml)
    out_musicxml.parent.mkdir(parents=True, exist_ok=True)
    score.write("musicxml", fp=str(out_musicxml))

    export_midi(score, instrument_key, out_midi)

    key = spelling.estimate_key(events)
    analysis = analyze_mod.analyze(events, _grid(score, duration_s), key,
                                   duration_s=duration_s)
    analysis["instrument"] = get_instrument(instrument_key).display_name
    return {
        "midi_path": Path(out_midi),
        "musicxml_path": out_musicxml,
        "analysis": analysis,
    }
