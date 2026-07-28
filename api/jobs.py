"""Background job runner.

Transcription takes minutes, not milliseconds, so the pipeline must run off the
request thread. This uses a thread-backed executor — simple, in-process, good
enough for a single-box demo. Swap ``submit_*`` for a Celery task when you need
multiple workers or restart durability; the DB rows are the queue either way.

Two job kinds share one runner: transcribing an uploaded recording, and
synthesizing uploaded sheet music back to audio.
"""

from __future__ import annotations

import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from piano_transcribe.importscore import ScoreImportError
from piano_transcribe.pipeline import Rejected, run_pipeline
from piano_transcribe.synthesize import midi_to_wav, synthesize

from . import db

# Single background worker; raise max_workers for parallel jobs (mind the RAM
# cost of multiple TensorFlow sessions).
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="transcribe")

MUSICXML_DIR = db.DATA_DIR / "musicxml"
AUDIO_DIR = db.DATA_DIR / "audio"
MIDI_DIR = db.DATA_DIR / "midi"


def submit_file_job(job_id: str, audio_path: str, instrument: str, title: str) -> None:
    """Queue a pipeline run for an already-saved audio file."""
    _executor.submit(_run_file, job_id, audio_path, instrument, title)


def _run_pipeline_into_db(job_id: str, audio_path: str, instrument: str, title: str) -> None:
    MUSICXML_DIR.mkdir(parents=True, exist_ok=True)
    out_path = MUSICXML_DIR / f"{job_id}.musicxml"
    try:
        result = run_pipeline(audio_path, out_path, instrument=instrument, title=title)
    except Rejected as exc:
        db.update_job(job_id, status=db.STATUS_REJECTED, error=str(exc))
        return
    db.update_job(
        job_id,
        status=db.STATUS_DONE,
        musicxml_path=str(result.musicxml_path or out_path),
        # The pipeline also renders the written score to MIDI/WAV so it can be
        # played back and compared against the original recording.
        midi_path=str(result.midi_path) if result.midi_path else None,
        analysis=json.dumps(result.analysis),
    )


def _run_file(job_id: str, audio_path: str, instrument: str, title: str) -> None:
    db.update_job(job_id, status=db.STATUS_RUNNING)
    try:
        _run_pipeline_into_db(job_id, audio_path, instrument, title)
    except Exception as exc:  # noqa: BLE001 - persist any failure for the client
        db.update_job(job_id, status=db.STATUS_FAILED,
                      error=f"{exc}\n{traceback.format_exc()}")


def submit_synthesize_job(job_id: str, sheet_path: str, instrument: str) -> None:
    """Queue a sheet-music -> MIDI synthesis run."""
    _executor.submit(_run_synthesize, job_id, sheet_path, instrument)


def _run_synthesize(job_id: str, sheet_path: str, instrument: str) -> None:
    db.update_job(job_id, status=db.STATUS_RUNNING)
    try:
        MUSICXML_DIR.mkdir(parents=True, exist_ok=True)
        MIDI_DIR.mkdir(parents=True, exist_ok=True)
        out_xml = MUSICXML_DIR / f"{job_id}.musicxml"
        out_mid = MIDI_DIR / f"{job_id}.mid"
        job = db.get_job(job_id)
        title = Path(job["filename"]).stem if job and job["filename"] else None
        result = synthesize(sheet_path, out_mid, out_xml, instrument, title=title)
        # Best-effort offline audio render (fluidsynth + soundfont). If it's
        # unavailable the frontend falls back to browser-side MIDI playback.
        midi_to_wav(out_mid, out_mid.with_suffix(".wav"))
        db.update_job(
            job_id,
            status=db.STATUS_DONE,
            musicxml_path=str(result["musicxml_path"]),
            midi_path=str(result["midi_path"]),
            analysis=json.dumps(result["analysis"]),
        )
    except ScoreImportError as exc:
        db.update_job(job_id, status=db.STATUS_REJECTED, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        db.update_job(job_id, status=db.STATUS_FAILED,
                      error=f"{exc}\n{traceback.format_exc()}")
