"""SQLite persistence for transcription jobs.

One table, ``jobs``. Audio and MusicXML live on the filesystem (paths stored
here), which keeps the DB small and the blobs streamable.

Schema is created on demand via :func:`init_db`; connections use row factory
for dict-like access and are short-lived (opened per request/task).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

# Job lifecycle states.
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"       # an unexpected error
STATUS_REJECTED = "rejected"   # audio judged not transcribable (with a reason)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "jobs.sqlite"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open the jobs database.

    ``DB_PATH`` is read at call time rather than bound as a default argument —
    a default would freeze the path at import, so redirecting the database
    (tests pointing at a temp dir, or a deployment overriding the location)
    would silently keep writing to the original file.
    """
    db_path = Path(db_path) if db_path is not None else DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id            TEXT PRIMARY KEY,
                user_id       INTEGER,
                status        TEXT NOT NULL,
                kind          TEXT NOT NULL DEFAULT 'transcribe',
                title         TEXT,
                filename      TEXT,
                instrument    TEXT,
                audio_path    TEXT,
                musicxml_path TEXT,
                midi_path     TEXT,
                analysis      TEXT,
                error         TEXT,
                created_at    REAL NOT NULL,
                updated_at    REAL NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id, created_at)")
        conn.commit()


def create_job(
    job_id: str,
    filename: str,
    audio_path: str | None,
    instrument: str = "piano",
    status: str = STATUS_QUEUED,
    kind: str = "transcribe",
    user_id: int | None = None,
    title: str | None = None,
) -> None:
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO jobs
               (id, user_id, status, kind, title, filename, instrument,
                audio_path, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, user_id, status, kind, title, filename, instrument,
             audio_path, now, now),
        )
        conn.commit()


def list_jobs(user_id: int, limit: int = 100, offset: int = 0) -> list[dict]:
    """A user's saved work, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, kind, status, title, filename, instrument, analysis,
                      musicxml_path, midi_path, created_at
               FROM jobs WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (user_id, limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


def count_jobs(user_id: int) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE user_id = ?", (user_id,)
        ).fetchone()
    return int(row["n"])


def delete_job(job_id: str) -> None:
    """Remove a job row and the files it owns."""
    from pathlib import Path

    job = get_job(job_id)
    if job is None:
        return
    for key in ("audio_path", "musicxml_path", "midi_path"):
        path = job.get(key)
        if not path:
            continue
        for candidate in (Path(path), Path(path).with_suffix(".wav")):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass  # a file we can't remove shouldn't block deleting the row
    with _connect() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as conn:
        conn.execute(
            f"UPDATE jobs SET {cols} WHERE id = ?",
            (*fields.values(), job_id),
        )
        conn.commit()


def get_job(job_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None
