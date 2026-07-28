"""End-to-end orchestration: audio file -> MusicXML + analysis.

The single entry point the API's background job and the eval CLI both call.
Instrument-aware: the chosen instrument sets the transcription pitch range, the
staff layout, and any written-vs-sounding transposition.

Raises :class:`Rejected` when the transcribability gate decides the audio can't
be turned into single-instrument sheet music (too dense, too short, speech…).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import analyze as analyze_mod
from . import beats, cleanup, evaluate, notate, quantize, quality, spelling, synthesize, voices
from .instruments import Instrument, get_instrument
from .transcribe import Transcriber, default_transcriber, transcribe
from .types import NoteEvent


class Rejected(Exception):
    """Raised when the audio is judged not transcribable to sheet music."""


@dataclass
class PipelineResult:
    """Everything a stage or the API might want to inspect or persist."""

    events: list[NoteEvent]
    musicxml_path: Path | None = None
    midi_path: Path | None = None
    analysis: dict = field(default_factory=dict)
    instrument: str = "piano"


def _transpose(events: list[NoteEvent], semitones: int) -> list[NoteEvent]:
    """Written-pitch copy of ``events`` (sounding + semitones); identity at 0."""
    if semitones == 0:
        return events
    return [
        NoteEvent(e.pitch + semitones, e.onset_s, e.offset_s, e.velocity)
        for e in events
    ]


def run_pipeline(
    audio_path: str | Path,
    out_musicxml: str | Path,
    instrument: Instrument | str | None = None,
    transcriber: Transcriber | None = None,
    title: str = "Untitled",
    gate: bool = True,
) -> PipelineResult:
    """Run audio -> MusicXML + analysis for one instrument.

    Stages: transcribe -> gate -> beats -> quantize -> voices -> (transpose) ->
    spelling -> notate, then compute the analysis summary.
    """
    audio_path = Path(audio_path)
    inst = instrument if isinstance(instrument, Instrument) else get_instrument(instrument)

    # Pick the best model for the instrument: the dedicated piano model when
    # transcribing piano (measured F1 0.98 vs 0.71 for basic-pitch on sampled
    # piano), otherwise basic-pitch band-limited to the instrument's range.
    if transcriber is None:
        transcriber = default_transcriber(
            inst.key,
            minimum_frequency=inst.freq_min,
            maximum_frequency=inst.freq_max,
        )
    events = transcribe(audio_path, transcriber=transcriber)
    # Strip transcription artifacts (harmonic ghosts, specks, split fragments)
    # before anything downstream turns them into notation.
    events = cleanup.clean_events(events)

    import librosa

    duration_s = float(librosa.get_duration(path=str(audio_path)))

    if gate:
        verdict = quality.assess_transcription(events, duration_s)
        if not verdict.ok:
            raise Rejected(verdict.reason)

    grid = beats.track_beats(audio_path, events)
    # Cost-based quantization reads rhythm better than nearest-subdivision
    # snapping (it weighs timing fidelity against notational complexity).
    quantized = quantize.quantize_cost(events, grid)

    if inst.notation == "grand":
        # Cost-based hand assignment keeps chords/lines on a sensible staff
        # instead of hard-splitting at middle C.
        voices.assign_cost(quantized)
    else:
        for q in quantized:
            q.staff, q.voice = 1, 1

    # Notation uses written pitch (sounding + transposition); analysis reports
    # the concert-pitch key from the sounding events.
    written = _transpose(events, inst.transposition)
    written_key = spelling.estimate_key(written)
    names = spelling.spell_notes(written, written_key)

    score = notate.build_score(
        quantized, grid, written_key, note_names=names, instrument=inst, title=title
    )
    xml_path = notate.export_musicxml(score, out_musicxml)

    sounding_key = spelling.estimate_key(events)
    analysis = analyze_mod.analyze(events, grid, sounding_key, duration_s=duration_s)
    analysis["instrument"] = inst.display_name
    # How faithfully the notation represents the performance — lets the UI (and
    # the user) judge the score without needing ground truth.
    analysis["fidelity"] = evaluate.notation_fidelity(events, quantized, grid)

    # Render the *written* score back to audio so it can be played against the
    # original recording: hearing the transcription is the most direct way to
    # judge whether it is right.
    midi_path = None
    try:
        midi_path = synthesize.export_midi(score, inst.key, Path(out_musicxml).with_suffix(".mid"))
        synthesize.midi_to_wav(midi_path, midi_path.with_suffix(".wav"))
    except Exception:  # noqa: BLE001 - playback is a convenience, never fatal
        midi_path = None

    return PipelineResult(
        events=events, musicxml_path=xml_path, midi_path=midi_path,
        analysis=analysis, instrument=inst.key,
    )
