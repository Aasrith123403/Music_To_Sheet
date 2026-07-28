"""Source separation — split a mix into stems for sampling and analysis.

This is deliberately a *separate tool* from transcription, not a change to it.
The project's transcription constraint still holds (one instrument in, notation
out); what stems add is a way to get that single instrument out of a mixed
recording in the first place, plus clean parts to sample.

Uses Demucs (hybrid transformer). Two models:

* ``htdemucs``    — 4 stems: drums, bass, other, vocals. Faster, very solid.
* ``htdemucs_6s`` — 6 stems: adds **piano** and **guitar**. Slower, and the
  piano stem in particular is imperfect, but it is the one that feeds
  transcription, so it is the default here.

Separation is heavy: expect roughly real-time on Apple GPU (MPS) and several
times slower on CPU. Everything imports lazily so the rest of the app doesn't
pay for torch.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "htdemucs_6s"

MODELS = {
    "htdemucs": {
        "label": "Standard (4 stems)",
        "stems": ["drums", "bass", "other", "vocals"],
        "note": "Faster and the most reliable separation.",
    },
    "htdemucs_6s": {
        "label": "Extended (6 stems)",
        "stems": ["drums", "bass", "other", "vocals", "piano", "guitar"],
        "note": "Adds piano and guitar; slower, and those two are the least clean.",
    },
}

# Stems worth handing to the transcriber, best first.
TRANSCRIBABLE_STEMS = ("piano", "guitar", "other", "vocals", "bass")

MAX_DURATION_S = 8 * 60


class StemError(Exception):
    """Raised when separation can't run or the input is unsuitable."""


@dataclass
class StemResult:
    name: str
    path: Path
    duration_s: float


def list_models() -> list[dict]:
    return [
        {"key": key, **{k: v for k, v in meta.items()}}
        for key, meta in MODELS.items()
    ]


def _device() -> str:
    """Prefer Apple GPU, then CUDA, then CPU."""
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def separate(
    audio_path: str | Path,
    out_dir: str | Path,
    model: str = DEFAULT_MODEL,
    progress: bool = False,
) -> list[StemResult]:
    """Split ``audio_path`` into stems written under ``out_dir``.

    Returns one :class:`StemResult` per stem. Raises :class:`StemError` for
    unusable input or a missing/failed model.
    """
    audio_path = Path(audio_path)
    out_dir = Path(out_dir)
    if not audio_path.exists():
        raise StemError("The audio file is missing.")
    if model not in MODELS:
        raise StemError(f"Unknown separation model '{model}'.")

    import soundfile as sf
    import torch

    try:
        info = sf.info(str(audio_path))
        duration = float(info.duration)
    except Exception as exc:  # noqa: BLE001
        raise StemError(f"Couldn't read the audio: {exc}") from exc
    if duration > MAX_DURATION_S:
        raise StemError(
            f"Track is {duration / 60:.1f} min; the limit for separation is "
            f"{MAX_DURATION_S // 60} minutes."
        )

    try:
        from demucs.api import Separator
    except ImportError as exc:
        raise StemError("Separation needs demucs: pip install demucs") from exc

    device = _device()
    try:
        separator = Separator(model=model, device=device, progress=progress)
        _origin, sources = separator.separate_audio_file(str(audio_path))
    except Exception as exc:  # noqa: BLE001 - model download / OOM / unsupported
        # MPS occasionally lacks an op; CPU is slower but always works.
        if device != "cpu":
            try:
                separator = Separator(model=model, device="cpu", progress=progress)
                _origin, sources = separator.separate_audio_file(str(audio_path))
            except Exception as exc2:  # noqa: BLE001
                raise StemError(f"Separation failed: {exc2}") from exc2
        else:
            raise StemError(f"Separation failed: {exc}") from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[StemResult] = []
    for name, tensor in sources.items():
        path = out_dir / f"{name}.wav"
        data = tensor.detach().cpu().numpy().T  # (channels, samples) -> (samples, channels)
        sf.write(str(path), data, separator.samplerate)
        results.append(StemResult(name=name, path=path, duration_s=duration))

    if not results:
        raise StemError("Separation produced no stems.")
    results.sort(key=lambda r: MODELS[model]["stems"].index(r.name)
                 if r.name in MODELS[model]["stems"] else 99)
    return results


def stem_summary(path: str | Path) -> dict:
    """Cheap signal stats so a stem can be judged without listening to it all."""
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(str(path), always_2d=True)
    mono = data.mean(axis=1)
    if mono.size == 0:
        return {"peak": 0.0, "rms": 0.0, "silent": True}
    peak = float(np.max(np.abs(mono)))
    rms = float(np.sqrt(np.mean(mono ** 2)))
    return {
        "peak": round(peak, 4),
        "rms": round(rms, 4),
        # Demucs always emits every stem, even when the instrument isn't there;
        # flagging the empty ones saves the user auditioning silence.
        "silent": bool(rms < 1e-3),
        "duration_s": round(len(mono) / sr, 2),
    }
