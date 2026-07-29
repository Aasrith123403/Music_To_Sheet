import { useEffect, useRef, useState } from "react";
import { OpenSheetMusicDisplay } from "opensheetmusicdisplay";
import AnalysisPanel from "./AnalysisPanel.jsx";
import MidiPlayer from "./MidiPlayer.jsx";
import { midiToName, playChord, playNote, primeAudio } from "./audio.js";
import { attachNoteClicks, buildSchedule, followAlong } from "./scoreInteraction.js";

/**
 * Robustly render a MusicXML URL with OSMD.
 * Fixes the "blank score" bug: OSMD is recreated per load, and render() is
 * deferred until the container actually has a width (via ResizeObserver), so a
 * render that happens before layout no longer produces an empty 0-width SVG.
 */
function useOsmd(musicxmlUrl) {
  const containerRef = useRef(null);
  const osmdRef = useRef(null);
  const [error, setError] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!musicxmlUrl) return;
    let cancelled = false;
    let observer = null;
    setError(null);
    setReady(false);

    (async () => {
      try {
        const res = await fetch(musicxmlUrl);
        if (!res.ok) throw new Error(`fetch failed (${res.status})`);
        const xml = await res.text();
        if (cancelled) return;

        if (osmdRef.current) {
          try {
            osmdRef.current.clear();
          } catch {
            /* ignore */
          }
        }
        const osmd = new OpenSheetMusicDisplay(containerRef.current, {
          autoResize: true,
          drawTitle: true,
          drawPartNames: false,
          backend: "svg",
          // OSMD's own cursor-following scrolls the page on every `cursor.next()`
          // and offers no way to suspend it, which pinned the reader to the
          // cursor: the transport controls sit above the score, so they scrolled
          // out of reach and scrolling back was undone by the next note. We do
          // the scrolling ourselves in `scrollCursorIntoView`, which yields as
          // soon as the reader scrolls by hand.
          followCursor: false,
        });
        osmdRef.current = osmd;
        await osmd.load(xml);
        if (cancelled) return;

        const tryRender = () => {
          const w = containerRef.current?.clientWidth || 0;
          if (w <= 0) return false;
          try {
            osmd.render();
            setReady(true);
          } catch (e) {
            setError(`Could not draw the score: ${e.message}`);
          }
          return true;
        };

        if (!tryRender()) {
          observer = new ResizeObserver(() => {
            if (tryRender() && observer) {
              observer.disconnect();
              observer = null;
            }
          });
          observer.observe(containerRef.current);
        }
      } catch (e) {
        if (!cancelled) setError(`Could not render score: ${e.message}`);
      }
    })();

    return () => {
      cancelled = true;
      if (observer) observer.disconnect();
    };
  }, [musicxmlUrl]);

  return { containerRef, osmdRef, error, ready };
}

async function downloadPdf(container, filename) {
  const { jsPDF } = await import("jspdf");
  await import("svg2pdf.js");
  const svgs = [...container.querySelectorAll("svg")];
  if (!svgs.length) return;

  const first = svgs[0];
  const w0 = first.width.baseVal.value || parseFloat(first.getAttribute("width"));
  const pdf = new jsPDF({
    orientation: w0 > 842 ? "landscape" : "portrait",
    unit: "pt",
    format: "a4",
  });

  const margin = 24;
  for (let i = 0; i < svgs.length; i++) {
    if (i > 0) pdf.addPage();
    const svg = svgs[i];
    const sw = svg.width.baseVal.value || parseFloat(svg.getAttribute("width"));
    const sh = svg.height.baseVal.value || parseFloat(svg.getAttribute("height"));
    const pw = pdf.internal.pageSize.getWidth() - margin * 2;
    const ph = pdf.internal.pageSize.getHeight() - margin * 2;
    const scale = Math.min(pw / sw, ph / sh, 1);
    // eslint-disable-next-line no-await-in-loop
    await pdf.svg(svg, { x: margin, y: margin, width: sw * scale, height: sh * scale });
  }
  pdf.save(filename);
}

export default function ScoreResult({ job }) {
  const musicxmlUrl = job.musicxml_ready ? `/jobs/${job.job_id}/musicxml` : null;
  const midiUrl = job.midi_ready ? `/jobs/${job.job_id}/midi` : null;
  const audioUrl = job.audio_ready ? `/jobs/${job.job_id}/audio` : null;

  const [pdfBusy, setPdfBusy] = useState(false);
  const [follow, setFollow] = useState(true);
  const [lastNote, setLastNote] = useState(null);
  const [rate, setRate] = useState(1);
  // Playback state, surfaced so the floating bar can appear while following.
  const [playing, setPlaying] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const audioRef = useRef(null);
  const midiRef = useRef(null);
  const scheduleRef = useRef([]);
  const detachRef = useRef(null);
  const stopFollowRef = useRef(null);

  const bpm = job.analysis?.tempo_bpm || 120;

  const { containerRef, osmdRef, error, ready } = useOsmd(musicxmlUrl);

  // Wire up clicking and build the playback schedule once a score is on screen.
  // This runs *after* rendering settles and reads `osmdRef.current` lazily, so
  // it always targets the instance actually displayed — binding during the
  // render callback attached listeners to an SVG that was replaced moments later.
  useEffect(() => {
    if (!ready) return undefined;
    const getOsmd = () => osmdRef.current;
    scheduleRef.current = buildSchedule(osmdRef.current, bpm);
    const detach = attachNoteClicks(
      getOsmd,
      (midis) => {
        primeAudio();
        playChord(midis);
        setLastNote(midis[0]);
      },
      containerRef.current
    );
    detachRef.current = detach;
    return () => {
      detach();
      detachRef.current = null;
    };
  }, [ready, bpm, musicxmlUrl, osmdRef, containerRef]);

  // Follow-along: drive the cursor from whichever transport is on screen.
  //
  // There are two: an <audio> element when the server rendered a WAV, and the
  // <midi-player> web component when it couldn't. Both expose `currentTime` in
  // seconds — all `followAlong` needs — but they signal playback differently,
  // so only the event names are switched here. Binding to `audioRef` alone was
  // why following worked locally (fluidsynth present, so a WAV existed) and
  // silently did nothing in deployment (no WAV, so no <audio> to bind to).
  useEffect(() => {
    const transport = audioRef.current || midiRef.current;
    const osmd = osmdRef.current;
    if (!transport || !osmd || !ready || !follow) return undefined;

    const isMidi = !audioRef.current;
    const startEvents = isMidi ? ["start"] : ["play"];
    const stopEvents = isMidi ? ["stop"] : ["pause", "ended"];

    const start = () => {
      stopFollowRef.current?.stop();
      setAutoScroll(true);
      setPlaying(true);
      stopFollowRef.current = followAlong(osmd, transport, scheduleRef.current, {
        container: containerRef.current,
        onAutoScroll: setAutoScroll,
      });
    };
    const stop = () => {
      stopFollowRef.current?.stop();
      stopFollowRef.current = null;
      setPlaying(false);
    };

    startEvents.forEach((e) => transport.addEventListener(e, start));
    stopEvents.forEach((e) => transport.addEventListener(e, stop));
    // Already playing when the score finished rendering.
    if (isMidi ? transport.playing : !transport.paused) start();

    return () => {
      startEvents.forEach((e) => transport.removeEventListener(e, start));
      stopEvents.forEach((e) => transport.removeEventListener(e, stop));
      stop();
    };
  }, [ready, follow, osmdRef, containerRef, audioUrl, midiUrl]);

  const baseName = (job.title || job.filename || "score").replace(/\.[^.]+$/, "");

  async function onPdf() {
    setPdfBusy(true);
    try {
      await downloadPdf(containerRef.current, `${baseName}.pdf`);
    } finally {
      setPdfBusy(false);
    }
  }

  /** Halt playback from anywhere on the page. */
  function pausePlayback() {
    if (audioRef.current) audioRef.current.pause();
    else midiRef.current?.stop();
  }

  /** Step the cursor by hand and sound whatever is under it. */
  function stepAndPlay(direction) {
    const osmd = osmdRef.current;
    const schedule = scheduleRef.current;
    if (!osmd?.cursor || !schedule.length) return;
    primeAudio();
    const cursor = osmd.cursor;
    cursor.show();
    if (direction > 0) cursor.next();
    else cursor.previous?.();
    const midis = (cursor.NotesUnderCursor() || [])
      .filter((n) => !n.isRestFlag)
      .map((n) => n.halfTone + 12);
    if (midis.length) {
      playChord(midis);
      setLastNote(midis[0]);
    }
  }

  return (
    <>
      {job.analysis && <AnalysisPanel analysis={job.analysis} />}

      {(audioUrl || midiUrl) && (
        <div className="card playback">
          <div className="section-head">
            <span>
              {job.kind === "synthesize" ? "Playback" : "Playback of the written score"}
            </span>
            <span className="playback-controls">
              <label className="toggle">
                Speed
                <select
                  value={rate}
                  // The MIDI fallback player has no rate control, so rather
                  // than leave a dead dropdown it is disabled and says why.
                  disabled={!audioUrl}
                  title={
                    audioUrl
                      ? undefined
                      : "Speed needs the server-rendered audio, which isn’t available for this score."
                  }
                  onChange={(e) => {
                    const r = Number(e.target.value);
                    setRate(r);
                    // Slowing a passage down is the main way to learn it.
                    if (audioRef.current) audioRef.current.playbackRate = r;
                  }}
                >
                  {[0.5, 0.75, 1, 1.25, 1.5].map((r) => (
                    <option key={r} value={r}>{r}×</option>
                  ))}
                </select>
              </label>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={follow}
                  onChange={(e) => setFollow(e.target.checked)}
                />
                Follow the score
              </label>
            </span>
          </div>
          {job.kind !== "synthesize" && (
            <p className="footnote playback-note">
              This is the transcription played back. Compare it with your
              original recording — if they match, the score is right.
            </p>
          )}
          {audioUrl ? (
            <audio ref={audioRef} className="audio-player" controls src={audioUrl} />
          ) : (
            <MidiPlayer ref={midiRef} src={midiUrl} />
          )}
        </div>
      )}

      <div className="card score-card">
        <div className="score-head">
          <span>Score</span>
          <span className="score-actions">
            <button className="link-btn" onClick={onPdf} disabled={!ready || pdfBusy}>
              {pdfBusy ? "Preparing…" : "↓ PDF"}
            </button>
            {musicxmlUrl && (
              <a className="link-btn" href={musicxmlUrl} download={`${baseName}.musicxml`}>
                ↓ MusicXML
              </a>
            )}
            {midiUrl && (
              <a className="link-btn" href={midiUrl} download={`${baseName}.mid`}>
                ↓ MIDI
              </a>
            )}
            {audioUrl && (
              <a className="link-btn" href={audioUrl} download={`${baseName}.wav`}>
                ↓ WAV
              </a>
            )}
          </span>
        </div>

        {ready && (
          <div className="score-toolbar">
            <span className="hint-inline">
              Click any note to hear it
              {lastNote != null && (
                <em className="heard"> — {midiToName(lastNote)}</em>
              )}
            </span>
            <span className="stepper">
              <button className="link-btn" onClick={() => stepAndPlay(-1)}>
                ‹ Prev
              </button>
              <button className="link-btn" onClick={() => stepAndPlay(1)}>
                Next ›
              </button>
            </span>
          </div>
        )}

        {error && <div className="score-error">{error}</div>}
        <div className="score" ref={containerRef} />
      </div>

      {/* Floating transport. The real controls live above the score, so once
          following scrolled the page down they were out of reach and there was
          no way to stop the audio. This stays put. */}
      {playing && follow && (
        <div className="follow-bar" role="toolbar" aria-label="Playback">
          <button className="follow-stop" onClick={pausePlayback} aria-label="Pause">
            ❚❚ Pause
          </button>
          <span className="follow-sep" />
          {autoScroll ? (
            <span className="follow-state">Following the score</span>
          ) : (
            <button
              className="link-btn"
              onClick={() => stopFollowRef.current?.setAutoScroll(true)}
            >
              ↻ Re-centre
            </button>
          )}
          <button className="link-btn" onClick={() => setFollow(false)}>
            Stop following
          </button>
        </div>
      )}
    </>
  );
}
