"""Audio -> note events.

The model lives behind the :class:`Transcriber` interface so a stronger
piano-specific model can replace basic-pitch without touching anything
downstream: every consumer only depends on ``list[NoteEvent]``.

basic-pitch pulls in TensorFlow, which is heavy and slow to import, so the
import is deferred into :meth:`BasicPitchTranscriber.transcribe`. Importing
this module (e.g. from tests) does not require basic-pitch to be installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .types import NoteEvent


@runtime_checkable
class Transcriber(Protocol):
    """Anything that turns an audio file into note events.

    Implementations must be deterministic for a given audio file and must emit
    notes sorted by onset time.
    """

    def transcribe(self, audio_path: str | Path) -> list[NoteEvent]:
        ...


def _amplitude_to_velocity(amplitude: float) -> int:
    """Map a 0..1 note amplitude to a 1..127 MIDI velocity, clamped."""
    v = int(round(amplitude * 127))
    return max(1, min(127, v))


class BasicPitchTranscriber:
    """Reference transcriber backed by Spotify's basic-pitch.

    Args:
        onset_threshold: Minimum onset confidence (0..1). Higher = fewer,
            more confident notes. Defaults to 0.7 rather than basic-pitch's own
            0.5: the model's recall is already saturated well above that, so the
            extra confidence buys precision (measurably fewer spurious notes)
            for free. See ``cli/bench_quantize.py`` for the measurement loop.
        frame_threshold: Minimum frame (sustain) confidence (0..1).
        minimum_note_length_ms: Drop notes shorter than this, in milliseconds.
        minimum_frequency / maximum_frequency: Optional Hz band-limit. Leave
            ``None`` for the full range; a standard piano is ~27.5-4186 Hz.
    """

    def __init__(
        self,
        onset_threshold: float = 0.7,
        frame_threshold: float = 0.3,
        minimum_note_length_ms: float = 58.0,
        minimum_frequency: float | None = None,
        maximum_frequency: float | None = None,
    ) -> None:
        self.onset_threshold = onset_threshold
        self.frame_threshold = frame_threshold
        self.minimum_note_length_ms = minimum_note_length_ms
        self.minimum_frequency = minimum_frequency
        self.maximum_frequency = maximum_frequency

    def transcribe(self, audio_path: str | Path) -> list[NoteEvent]:
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(audio_path)

        # Deferred import: keeps TensorFlow out of the import path for anything
        # that doesn't actually run the model.
        from basic_pitch import ICASSP_2022_MODEL_PATH
        from basic_pitch.inference import predict

        _model_output, _midi_data, note_rows = predict(
            str(audio_path),
            model_or_model_path=ICASSP_2022_MODEL_PATH,
            onset_threshold=self.onset_threshold,
            frame_threshold=self.frame_threshold,
            minimum_note_length=self.minimum_note_length_ms,
            minimum_frequency=self.minimum_frequency,
            maximum_frequency=self.maximum_frequency,
        )

        # basic-pitch note rows: (start_s, end_s, pitch_midi, amplitude, pitch_bends)
        events = [
            NoteEvent(
                pitch=int(pitch_midi),
                onset_s=float(start_s),
                offset_s=float(end_s),
                velocity=_amplitude_to_velocity(float(amplitude)),
            )
            for (start_s, end_s, pitch_midi, amplitude, *_rest) in note_rows
        ]
        events.sort(key=lambda e: (e.onset_s, e.pitch))
        return events


class PianoTranscriber:
    """High-resolution piano transcription (ByteDance / `piano_transcription_inference`).

    Purpose-built for solo piano, and markedly more accurate on it than the
    general-purpose basic-pitch: it predicts onsets, offsets, velocities and
    pedal at high time resolution, so it produces far fewer of the harmonic
    ghosts and split notes that the notation layer then has to clean up.

    The trade-off is scope — it only knows piano — so it's used when the chosen
    instrument is piano and basic-pitch remains the fallback for everything
    else. The checkpoint (~170 MB) downloads on first use.
    """

    def __init__(self, device: str | None = None) -> None:
        self.device = device

    def _resolve_device(self) -> str:
        if self.device:
            return self.device
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        # The model's CUDA kernels don't map onto MPS, so CPU is the safe default
        # on Apple silicon; it is still fast enough for a few minutes of audio.
        return "cpu"

    # Silence prepended before inference so notes at t=0 are still detected.
    LEAD_IN_S = 0.5

    CHECKPOINT_URL = (
        "https://zenodo.org/record/4034264/files/"
        "CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1"
    )
    CHECKPOINT_PATH = (
        Path.home() / "piano_transcription_inference_data"
        / "note_F1=0.9677_pedal_F1=0.9186.pth"
    )

    @classmethod
    def ensure_checkpoint(cls) -> Path:
        """Fetch the model weights if they're missing.

        The upstream package shells out to ``wget``, which macOS doesn't ship —
        the download fails silently and the model then dies on a missing file.
        Fetching it here with urllib keeps first run working everywhere.
        """
        path = cls.CHECKPOINT_PATH
        if path.exists() and path.stat().st_size > 1.6e8:
            return path
        import urllib.request

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(cls.CHECKPOINT_URL, tmp)  # noqa: S310
        tmp.replace(path)
        return path

    def transcribe(self, audio_path: str | Path) -> list[NoteEvent]:
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(audio_path)

        self.ensure_checkpoint()

        import librosa
        import numpy as np
        from piano_transcription_inference import PianoTranscription, sample_rate

        audio, _ = librosa.load(str(audio_path), sr=sample_rate, mono=True)

        # The model needs a moment of context before it will report an onset, so
        # anything struck in the first instant of a file is missed entirely —
        # measured as the *only* failure on an otherwise perfect transcription
        # (a recording that starts on a chord lost that whole chord). Prepending
        # silence and shifting the results back recovers it.
        pad = np.zeros(int(self.LEAD_IN_S * sample_rate), dtype=audio.dtype)
        padded = np.concatenate([pad, audio])

        model = PianoTranscription(device=self._resolve_device())
        output = model.transcribe(padded, None)

        events = []
        for n in output.get("est_note_events", []):
            onset = float(n["onset_time"]) - self.LEAD_IN_S
            offset = float(n["offset_time"]) - self.LEAD_IN_S
            if offset <= onset:
                continue
            events.append(
                NoteEvent(
                    pitch=int(n["midi_note"]),
                    onset_s=max(0.0, onset),
                    offset_s=max(1e-3, offset),
                    velocity=max(1, min(127, int(n.get("velocity", 80)))),
                )
            )
        events.sort(key=lambda e: (e.onset_s, e.pitch))
        return events


def piano_transcriber_available() -> bool:
    """Is the dedicated piano model installed?"""
    try:
        import piano_transcription_inference  # noqa: F401

        return True
    except ImportError:
        return False


def default_transcriber(instrument_key: str = "piano", **kwargs) -> Transcriber:
    """Best available model for the chosen instrument.

    Piano gets the dedicated piano model when it's installed; everything else
    (and piano without it) falls back to basic-pitch.
    """
    if instrument_key == "piano" and piano_transcriber_available():
        return PianoTranscriber()
    return BasicPitchTranscriber(**kwargs)


def transcribe(
    audio_path: str | Path, transcriber: Transcriber | None = None
) -> list[NoteEvent]:
    """Convenience wrapper: transcribe ``audio_path`` to note events.

    Uses :class:`BasicPitchTranscriber` with default settings unless a custom
    ``transcriber`` is supplied.
    """
    transcriber = transcriber or BasicPitchTranscriber()
    return transcriber.transcribe(audio_path)
