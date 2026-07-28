"""Load sheet music into a music21 Score, from several input formats.

Two tiers:
  * **Structured** (MusicXML / MIDI) — parsed directly by music21, exact.
  * **Optical** (PDF / image) — run through OMR to *guess* a MusicXML, then
    parsed. Best-effort: accuracy depends on the scan and the OMR engine.

Two OMR engines are supported, in order of preference:
  * **Audiveris** — a full OMR application (Java); more robust, handles PDFs and
    images directly. Selected when an ``audiveris`` launcher is available (on
    PATH, or via ``$AUDIVERIS_CMD`` / ``$AUDIVERIS_JAR``).
  * **oemer** — a pip-installable deep-learning OMR; lighter to install but
    fragile (it can crash on clean/synthetic images). Fallback.

``$PIANO_OMR_ENGINE`` forces one of ``audiveris`` / ``oemer`` (default ``auto``).
All heavy imports/subprocesses are deferred so structured files never pay.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

STRUCTURED_SUFFIXES = {".musicxml", ".xml", ".mxl", ".mid", ".midi"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


class ScoreImportError(Exception):
    """Raised when sheet music can't be read (bad file, OMR missing/failed)."""


def load_score(path: str | Path):  # -> music21.stream.Score
    """Load ``path`` into a music21 Score, dispatching on file extension."""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in STRUCTURED_SUFFIXES:
        from music21 import converter

        try:
            return converter.parse(str(path))
        except Exception as exc:  # noqa: BLE001
            raise ScoreImportError(f"Couldn't parse {suffix} file: {exc}") from exc

    if suffix == ".pdf" or suffix in IMAGE_SUFFIXES:
        return _omr_to_score(path)

    raise ScoreImportError(
        f"Unsupported sheet-music format '{suffix}'. Use MusicXML, MIDI, PDF, "
        "or an image."
    )


# ---------------------------------------------------------------------------
# OMR dispatch
# ---------------------------------------------------------------------------

def _omr_to_score(input_path: Path):
    from music21 import converter

    engine = os.environ.get("PIANO_OMR_ENGINE", "auto").lower()
    use_audiveris = engine in ("auto", "audiveris") and _audiveris_cmd() is not None

    if engine == "audiveris" and _audiveris_cmd() is None:
        raise ScoreImportError(
            "PIANO_OMR_ENGINE=audiveris but no Audiveris launcher was found "
            "(set $AUDIVERIS_CMD or $AUDIVERIS_JAR, or put 'audiveris' on PATH)."
        )

    if use_audiveris:
        musicxml = _run_audiveris(input_path)
    else:
        # oemer works on a single image; rasterise the PDF's first page first.
        image = _pdf_first_page_to_png(input_path) if input_path.suffix.lower() == ".pdf" else input_path
        musicxml = _run_oemer(image)

    try:
        return converter.parse(str(musicxml))
    except Exception as exc:  # noqa: BLE001
        raise ScoreImportError(f"OMR output couldn't be parsed: {exc}") from exc


# ---------------------------------------------------------------------------
# Audiveris
# ---------------------------------------------------------------------------

# Common install locations checked after PATH / env vars.
_AUDIVERIS_GUESSES = (
    Path.home() / "audiveris" / "bin" / "Audiveris",
    Path.home() / "audiveris" / "bin" / "audiveris",
)


def _audiveris_cmd() -> list[str] | None:
    """Command prefix to launch Audiveris, or ``None`` if unavailable."""
    cmd = os.environ.get("AUDIVERIS_CMD")
    if cmd:
        return [cmd]
    jar = os.environ.get("AUDIVERIS_JAR")
    if jar and Path(jar).exists():
        return ["java", "-jar", jar]
    found = shutil.which("audiveris") or shutil.which("Audiveris")
    if found:
        return [found]
    for guess in _AUDIVERIS_GUESSES:
        if guess.exists():
            return [str(guess)]
    return None


def _run_audiveris(input_path: Path) -> Path:
    """Run Audiveris in batch mode, returning the exported MusicXML (.mxl)."""
    cmd = _audiveris_cmd()
    if cmd is None:
        raise ScoreImportError("No Audiveris launcher available.")

    # Audiveris needs Tesseract OCR data; point it at a common brew location
    # if the caller hasn't already set TESSDATA_PREFIX.
    env = os.environ.copy()
    if "TESSDATA_PREFIX" not in env:
        for tessdata in ("/opt/homebrew/share/tessdata", "/usr/local/share/tessdata"):
            if Path(tessdata).is_dir():
                env["TESSDATA_PREFIX"] = tessdata
                break

    out_dir = Path(tempfile.mkdtemp())
    try:
        subprocess.run(
            [*cmd, "-batch", "-export", "-output", str(out_dir), "--", str(input_path)],
            check=True, capture_output=True, text=True, timeout=600, env=env,
        )
    except subprocess.CalledProcessError as exc:
        raise ScoreImportError(f"Audiveris OMR failed: {exc.stderr or exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ScoreImportError("Audiveris OMR timed out.") from exc

    produced = (
        list(out_dir.rglob("*.mxl"))
        or list(out_dir.rglob("*.musicxml"))
        or list(out_dir.rglob("*.xml"))
    )
    if not produced:
        raise ScoreImportError("Audiveris produced no MusicXML output.")
    return produced[0]


# ---------------------------------------------------------------------------
# oemer (fallback)
# ---------------------------------------------------------------------------

def _pdf_first_page_to_png(pdf_path: Path) -> Path:
    """Render the first PDF page to a PNG (300 dpi) for image-only OMR."""
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ScoreImportError("Reading PDFs needs PyMuPDF: pip install pymupdf") from exc

    doc = fitz.open(str(pdf_path))
    if doc.page_count == 0:
        raise ScoreImportError("The PDF has no pages.")
    pix = doc.load_page(0).get_pixmap(dpi=300)
    out = Path(tempfile.mkdtemp()) / "page.png"
    pix.save(str(out))
    return out


def _run_oemer(image_path: Path) -> Path:
    """Run oemer OMR on an image, returning the MusicXML path it produces."""
    try:
        import oemer  # noqa: F401
    except ImportError as exc:
        raise ScoreImportError(
            "No OMR engine available. Install Audiveris (recommended) or "
            "'oemer' (pip install oemer) to read PDFs/images."
        ) from exc

    # oemer downloads model checkpoints over HTTPS on first run; python.org
    # builds often lack CA certs, so point it at certifi's bundle if present.
    env = os.environ.copy()
    try:
        import certifi

        env.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass

    out_dir = Path(tempfile.mkdtemp())
    try:
        subprocess.run(
            ["oemer", str(image_path), "-o", str(out_dir)],
            check=True, capture_output=True, text=True, timeout=600, env=env,
        )
    except subprocess.CalledProcessError as exc:
        raise ScoreImportError(f"oemer OMR failed: {exc.stderr or exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ScoreImportError("oemer OMR timed out (the image may be too large).") from exc

    produced = list(out_dir.glob("*.musicxml")) or list(out_dir.glob("*.xml"))
    if not produced:
        raise ScoreImportError("oemer produced no MusicXML output.")
    return produced[0]
