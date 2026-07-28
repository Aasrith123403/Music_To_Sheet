"""FastAPI app.

Endpoints:
    GET  /instruments          instruments for the dropdown
    POST /auth/register        create an account
    POST /auth/login           sign in           (session cookie)
    POST /auth/logout          sign out
    GET  /auth/me              current user + whether Google sign-in is available
    GET  /auth/google/login    start Google OAuth (see api.google_oauth)
    POST /jobs                 upload audio -> queue the pipeline
    POST /jobs/youtube         transcribe a YouTube URL (private-study use)
    POST /synthesize           sheet music -> playable MIDI
    GET  /jobs/{id}            poll job status (+ analysis when done)
    GET  /jobs/{id}/musicxml   download the rendered MusicXML
    GET  /library              the signed-in user's saved work
    PATCH/DELETE /jobs/{id}    rename / delete a saved piece
    GET  /learn/quiz           note-reading flashcards
    GET  /learn/keys           circle-of-fifths reference

Signing in is optional: anonymous visitors can still transcribe, they just
can't save to a library.

Run:  uvicorn api.main:app --reload
"""

from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()



import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    Body, Cookie, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile,
)
from fastapi.responses import FileResponse

from piano_transcribe import chords as chords_mod
from piano_transcribe import learn, stems as stems_mod
from piano_transcribe.instruments import get_instrument, list_instruments

from . import auth, config, db, google_oauth, jobs, youtube

ALLOWED_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aiff"}
SHEET_SUFFIXES = {
    ".musicxml", ".xml", ".mxl", ".mid", ".midi",  # structured
    ".pdf", ".png", ".jpg", ".jpeg",               # optical (OMR)
}
AUDIO_DIR = db.DATA_DIR / "audio"
SHEET_DIR = db.DATA_DIR / "sheets"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Print the resolved Google config (credentials masked) — an unset or
    # malformed client id is the usual cause of Google's "invalid_client".
    print(config.describe(), flush=True)
    db.init_db()
    auth.init_auth_db()
    auth.purge_expired_sessions()
    # Resolved from db.DATA_DIR at startup rather than import, so a redirected
    # data directory (tests, deployments) doesn't leave stray dirs behind.
    (db.DATA_DIR / "audio").mkdir(parents=True, exist_ok=True)
    (db.DATA_DIR / "sheets").mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Audio -> Sheet Music", lifespan=lifespan)
app.include_router(google_oauth.router)


@app.get("/instruments")
def get_instruments() -> dict:
    """Instruments the UI can offer in its dropdown."""
    return {"instruments": list_instruments()}


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------

@app.post("/auth/register", status_code=201)
def register(response: Response, payload: dict = Body(...)) -> dict:
    """Create an account and sign in immediately."""
    user = auth.create_user(
        email=(payload.get("email") or "").strip(),
        password=payload.get("password") or "",
        name=(payload.get("name") or "").strip() or None,
    )
    auth.set_session_cookie(response, auth.create_session(user.id))
    return {"user": user.public()}


@app.post("/auth/login")
def login(response: Response, payload: dict = Body(...)) -> dict:
    user = auth.authenticate(
        email=(payload.get("email") or "").strip(),
        password=payload.get("password") or "",
    )
    auth.set_session_cookie(response, auth.create_session(user.id))
    return {"user": user.public()}


@app.post("/auth/logout")
def logout(response: Response, session: str | None = Cookie(default=None)) -> dict:
    """Revoke the current session server-side and clear the cookie."""
    if session:
        auth.delete_session(session)
    auth.clear_session_cookie(response)
    return {"ok": True}


@app.get("/auth/me")
def me(user: auth.User | None = Depends(auth.current_user)) -> dict:
    """Who am I, and is Google sign-in available on this server?"""
    return {
        "user": user.public() if user else None,
        "google_enabled": google_oauth.is_configured(),
    }


@app.post("/jobs", status_code=201)
async def create_job(
    file: UploadFile = File(...),
    instrument: str = Form("piano"),
    user: auth.User | None = Depends(auth.current_user),
) -> dict:
    """Accept a single-instrument audio file and queue a transcription job."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio type '{suffix}'. Allowed: {sorted(ALLOWED_SUFFIXES)}",
        )
    instrument = get_instrument(instrument).key  # normalise / validate

    job_id = uuid.uuid4().hex
    audio_path = AUDIO_DIR / f"{job_id}{suffix}"
    audio_path.write_bytes(await file.read())

    db.create_job(job_id, filename=file.filename or audio_path.name,
                  audio_path=str(audio_path), instrument=instrument,
                  user_id=user.id if user else None)
    jobs.submit_file_job(job_id, str(audio_path), instrument,
                         title=file.filename or "Untitled")
    return {"job_id": job_id, "status": db.STATUS_QUEUED}


@app.post("/jobs/youtube", status_code=201)
def create_youtube_job(
    payload: dict = Body(...),
    user: auth.User | None = Depends(auth.current_user),
) -> dict:
    """Queue a transcription job for a YouTube URL (private-study use only)."""
    url = (payload.get("url") or "").strip()
    instrument = get_instrument(payload.get("instrument")).key
    if not url:
        raise HTTPException(status_code=400, detail="Missing 'url'.")
    if not youtube.is_youtube_url(url):
        raise HTTPException(status_code=400, detail="Not a recognised YouTube URL.")

    job_id = uuid.uuid4().hex
    db.create_job(job_id, filename="YouTube audio", audio_path=None,
                  instrument=instrument, source_url=url,
                  user_id=user.id if user else None)
    jobs.submit_youtube_job(job_id, url, instrument)
    return {"job_id": job_id, "status": db.STATUS_QUEUED}


@app.post("/synthesize", status_code=201)
async def create_synthesis(
    file: UploadFile = File(...),
    instrument: str = Form("piano"),
    user: auth.User | None = Depends(auth.current_user),
) -> dict:
    """Accept sheet music (MusicXML/MIDI, or PDF/image via OMR) and synthesize
    it to a playable MIDI in the chosen instrument."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SHEET_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported sheet type '{suffix}'. Allowed: {sorted(SHEET_SUFFIXES)}",
        )
    instrument = get_instrument(instrument).key

    job_id = uuid.uuid4().hex
    sheet_path = SHEET_DIR / f"{job_id}{suffix}"
    sheet_path.write_bytes(await file.read())

    db.create_job(job_id, filename=file.filename or sheet_path.name,
                  audio_path=str(sheet_path), instrument=instrument,
                  kind="synthesize", user_id=user.id if user else None)
    jobs.submit_synthesize_job(job_id, str(sheet_path), instrument)
    return {"job_id": job_id, "status": db.STATUS_QUEUED}


def _accessible_job(job_id: str, user: auth.User | None) -> dict:
    """Fetch a job, enforcing ownership.

    A job belonging to an account is visible only to that account. Jobs created
    anonymously have no owner and stay reachable by their (unguessable) id, so
    signing out mid-transcription doesn't lose the result. A job owned by
    someone else reports 404 rather than 403 — confirming that an id exists
    tells a stranger more than it needs to.
    """
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    owner = job.get("user_id")
    if owner is not None and (user is None or user.id != owner):
        raise HTTPException(status_code=404, detail="Unknown job id")
    return job


def _job_payload(job: dict) -> dict:
    analysis = json.loads(job["analysis"]) if job["analysis"] else None
    if analysis:
        analysis.setdefault("difficulty", learn.score_difficulty(analysis))
    audio_ready = bool(job["midi_path"]) and Path(job["midi_path"]).with_suffix(".wav").exists()
    return {
        "job_id": job["id"],
        "status": job["status"],
        "kind": job["kind"],
        "title": job.get("title"),
        "filename": job["filename"],
        "instrument": job["instrument"],
        "source_url": job["source_url"],
        "error": job["error"],
        "musicxml_ready": bool(job["musicxml_path"]),
        "midi_ready": bool(job["midi_path"]),
        "audio_ready": audio_ready,
        "saved": job.get("user_id") is not None,
        "analysis": analysis,
    }


@app.get("/jobs/{job_id}")
def get_job(job_id: str, user: auth.User | None = Depends(auth.current_user)) -> dict:
    """Poll a job. Includes the analysis summary once done."""
    return _job_payload(_accessible_job(job_id, user))


@app.patch("/jobs/{job_id}")
def rename_job(job_id: str, payload: dict = Body(...),
               user: auth.User = Depends(auth.require_user)) -> dict:
    """Rename a saved piece."""
    _accessible_job(job_id, user)
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title can't be empty.")
    db.update_job(job_id, title=title[:200])
    return {"ok": True, "title": title[:200]}


@app.delete("/jobs/{job_id}")
def remove_job(job_id: str, user: auth.User = Depends(auth.require_user)) -> dict:
    """Delete a saved piece and the files it owns."""
    _accessible_job(job_id, user)
    db.delete_job(job_id)
    return {"ok": True}


@app.get("/library")
def library(limit: int = 100, offset: int = 0,
            user: auth.User = Depends(auth.require_user)) -> dict:
    """The signed-in user's saved work, newest first."""
    limit = max(1, min(limit, 200))
    items = []
    for row in db.list_jobs(user.id, limit=limit, offset=max(0, offset)):
        analysis = json.loads(row["analysis"]) if row["analysis"] else None
        items.append({
            "job_id": row["id"],
            "kind": row["kind"],
            "status": row["status"],
            "title": row["title"] or row["filename"],
            "instrument": row["instrument"],
            "created_at": row["created_at"],
            "key": (analysis or {}).get("key"),
            "tempo_bpm": (analysis or {}).get("tempo_bpm"),
            "duration_hms": (analysis or {}).get("duration_hms"),
            "difficulty": learn.score_difficulty(analysis) if analysis else None,
        })
    return {"items": items, "total": db.count_jobs(user.id)}


# ---------------------------------------------------------------------------
# learning
# ---------------------------------------------------------------------------

@app.get("/learn/quiz")
def learn_quiz(clef: str = "treble", count: int = 10, naturals_only: bool = True) -> dict:
    """Note-reading flashcards: engraved staves plus answers."""
    if clef not in learn.CLEF_RANGES:
        raise HTTPException(status_code=400, detail=f"Unknown clef '{clef}'.")
    return {"cards": learn.note_quiz(clef, count=max(1, min(count, 40)),
                                     naturals_only=naturals_only)}


# ---------------------------------------------------------------------------
# chords
# ---------------------------------------------------------------------------

@app.get("/chords/qualities")
def chord_qualities() -> dict:
    """Every chord quality the builder offers, plus note names."""
    return {
        "qualities": [
            {"key": key, "label": full, "intervals": list(iv)}
            for key, (full, iv) in chords_mod.QUALITIES.items()
        ],
        "notes": list(chords_mod.NOTE_NAMES_SHARP),
    }


@app.post("/chords/build")
def chord_build(payload: dict = Body(...)) -> dict:
    """Build a chord from a root + quality (+ inversion) and engrave it."""
    try:
        chord = chords_mod.build_chord(
            root_pc=int(payload.get("root", 0)),
            quality=str(payload.get("quality", "maj")),
            octave=int(payload.get("octave", 4)),
            inversion=int(payload.get("inversion", 0)),
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    out = chord.as_dict()
    out["musicxml"] = chords_mod.chord_musicxml(chord.pitches, chord.name)
    return out


@app.post("/chords/identify")
def chord_identify(payload: dict = Body(...)) -> dict:
    """Name an arbitrary set of pitches — 'what did I just play?'"""
    raw = payload.get("pitches") or []
    try:
        pitches = [int(p) for p in raw][:12]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="pitches must be MIDI numbers.")
    result = chords_mod.identify_chord(pitches)
    if pitches:
        result["musicxml"] = chords_mod.chord_musicxml(
            sorted(set(pitches)), result.get("name") or ""
        )
    return result


@app.get("/chords/key")
def chord_key(tonic: int = 0, mode: str = "major") -> dict:
    """Diatonic chords and common progressions in a key."""
    if mode not in ("major", "minor"):
        raise HTTPException(status_code=400, detail="mode must be major or minor.")
    return {
        "diatonic": chords_mod.diatonic_chords(int(tonic) % 12, mode),
        "progressions": chords_mod.progressions(int(tonic) % 12, mode),
    }


# ---------------------------------------------------------------------------
# stem separation
# ---------------------------------------------------------------------------

@app.get("/stems/models")
def stem_models() -> dict:
    """Separation models available, and whether the feature is installed."""
    try:
        import demucs  # noqa: F401

        available = True
    except ImportError:
        available = False
    return {"available": available, "models": stems_mod.list_models(),
            "default": stems_mod.DEFAULT_MODEL}


@app.post("/stems", status_code=201)
async def create_stems_job(
    file: UploadFile = File(...),
    model: str = Form(stems_mod.DEFAULT_MODEL),
    user: auth.User | None = Depends(auth.current_user),
) -> dict:
    """Split an uploaded track into stems."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio type '{suffix}'. Allowed: {sorted(ALLOWED_SUFFIXES)}",
        )
    if model not in stems_mod.MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model}'.")

    job_id = uuid.uuid4().hex
    audio_path = AUDIO_DIR / f"{job_id}{suffix}"
    audio_path.write_bytes(await file.read())

    db.create_job(job_id, filename=file.filename or audio_path.name,
                  audio_path=str(audio_path), instrument="piano",
                  kind="stems", user_id=user.id if user else None)
    jobs.submit_stems_job(job_id, str(audio_path), model)
    return {"job_id": job_id, "status": db.STATUS_QUEUED}


@app.get("/jobs/{job_id}/stems/{name}")
def get_stem(job_id: str, name: str,
             user: auth.User | None = Depends(auth.current_user)) -> FileResponse:
    """Stream one separated stem."""
    job = _accessible_job(job_id, user)
    if not job.get("stems_dir"):
        raise HTTPException(status_code=409, detail="Stems not ready.")
    # Guard against path traversal in the stem name.
    if not name.isalnum():
        raise HTTPException(status_code=400, detail="Bad stem name.")
    path = Path(job["stems_dir"]) / f"{name}.wav"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No '{name}' stem.")
    return FileResponse(path, media_type="audio/wav",
                        filename=f"{job_id}-{name}.wav")


@app.get("/learn/keys")
def learn_keys() -> dict:
    """Circle-of-fifths reference."""
    return {"keys": learn.key_signature_reference()}


@app.get("/jobs/{job_id}/musicxml")
def get_musicxml(job_id: str, user: auth.User | None = Depends(auth.current_user)) -> FileResponse:
    """Download the rendered MusicXML once the job is done."""
    job = _accessible_job(job_id, user)
    if job["status"] != db.STATUS_DONE or not job["musicxml_path"]:
        raise HTTPException(status_code=409, detail=f"MusicXML not ready (status={job['status']})")
    path = Path(job["musicxml_path"])
    if not path.exists():
        raise HTTPException(status_code=410, detail="MusicXML file missing on disk")
    return FileResponse(
        path, media_type="application/vnd.recordare.musicxml+xml",
        filename=f"{job_id}.musicxml",
    )


@app.get("/jobs/{job_id}/midi")
def get_midi(job_id: str, user: auth.User | None = Depends(auth.current_user)) -> FileResponse:
    """Download the synthesized MIDI once a synthesis job is done."""
    job = _accessible_job(job_id, user)
    if not job["midi_path"]:
        raise HTTPException(status_code=409, detail=f"MIDI not ready (status={job['status']})")
    path = Path(job["midi_path"])
    if not path.exists():
        raise HTTPException(status_code=410, detail="MIDI file missing on disk")
    return FileResponse(path, media_type="audio/midi", filename=f"{job_id}.mid")


@app.get("/jobs/{job_id}/audio")
def get_audio(job_id: str, user: auth.User | None = Depends(auth.current_user)) -> FileResponse:
    """Download the offline-rendered WAV (fluidsynth), when available."""
    job = _accessible_job(job_id, user)
    if not job["midi_path"]:
        raise HTTPException(status_code=409, detail=f"Audio not ready (status={job['status']})")
    path = Path(job["midi_path"]).with_suffix(".wav")
    if not path.exists():
        raise HTTPException(status_code=404, detail="No offline audio (fluidsynth unavailable)")
    return FileResponse(path, media_type="audio/wav", filename=f"{job_id}.wav")
