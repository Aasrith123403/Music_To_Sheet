"""Fetch audio from a YouTube URL for transcription.

Private-study use only: downloading conflicts with YouTube's Terms of Service
and most music is copyrighted, so generated scores must not be published.

Two entry points:
  * :func:`probe` — read metadata (title, duration) *without* downloading, so a
    too-long clip can be declined before we spend bandwidth;
  * :func:`download_audio` — extract the best audio track to a wav via ffmpeg.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

_ALLOWED_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "music.youtube.com", "youtu.be",
}


class YouTubeError(Exception):
    """Raised for invalid URLs or unavailable/undownloadable videos."""


def is_youtube_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _ALLOWED_HOSTS


@dataclass
class VideoInfo:
    title: str
    duration_s: float


def probe(url: str) -> VideoInfo:
    """Return title + duration without downloading. Raises :class:`YouTubeError`."""
    if not is_youtube_url(url):
        raise YouTubeError("Not a recognised YouTube URL.")
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # yt_dlp raises many subclasses
        raise YouTubeError(f"Could not read the video: {exc}") from exc

    duration = info.get("duration")
    if not duration:
        raise YouTubeError("The video has no duration (a live stream?).")
    return VideoInfo(title=info.get("title") or "YouTube audio", duration_s=float(duration))


def download_audio(url: str, out_dir: Path, job_id: str) -> Path:
    """Download and extract the audio track to ``out_dir/<job_id>.wav``."""
    if not is_youtube_url(url):
        raise YouTubeError("Not a recognised YouTube URL.")
    import yt_dlp

    out_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / f"{job_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "wav"}
        ],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
    except Exception as exc:
        raise YouTubeError(f"Download failed: {exc}") from exc

    wav = out_dir / f"{job_id}.wav"
    if not wav.exists():
        raise YouTubeError("Audio extraction produced no file (ffmpeg missing?).")
    return wav
