import { useEffect, useState } from "react";
import ScoreResult from "./ScoreResult.jsx";
import Library from "./Library.jsx";
import Learn from "./Learn.jsx";
import Chords from "./Chords.jsx";
import { AuthDialog, UserMenu } from "./AuthPanel.jsx";
import { api } from "./api.js";

const TERMINAL = ["done", "failed", "rejected"];
const SHEET_ACCEPT = ".musicxml,.xml,.mxl,.mid,.midi,.pdf,.png,.jpg,.jpeg";
// [key, nav label, what this tab is for]. The blurb is shown under the nav so a
// first-time visitor knows what to do on each page without having to poke at it.
const PAGES = [
  [
    "studio",
    "Studio",
    "Upload a piano recording and get sheet music back — or upload a score and hear it played.",
  ],
  [
    "chords",
    "Chords",
    "Build a chord from any root and quality, name one you already have, or browse the chords in a key.",
  ],
  [
    "library",
    "Library",
    "Everything you’ve transcribed, saved to your account. Open a score to view, play or download it.",
  ],
  [
    "learn",
    "Learn",
    "Practise reading notes, drill scales and chords with a metronome, and work through a piano routine.",
  ],
];

export default function App() {
  const [user, setUser] = useState(null);
  const [googleEnabled, setGoogleEnabled] = useState(false);
  const [showAuth, setShowAuth] = useState(false);
  const [page, setPage] = useState("studio");

  const [instruments, setInstruments] = useState([]);
  const [appMode, setAppMode] = useState("transcribe"); // transcribe | synthesize
  const [instrument, setInstrument] = useState("piano");
  const [audioFile, setAudioFile] = useState(null);
  const [sheetFile, setSheetFile] = useState(null);

  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.me()
      .then((d) => {
        setUser(d.user);
        setGoogleEnabled(d.google_enabled);
      })
      .catch(() => {});
    api.instruments().then((d) => setInstruments(d.instruments || [])).catch(() => {});

    const jobId = new URLSearchParams(window.location.search).get("job");
    if (jobId) api.job(jobId).then(setJob).catch(() => {});
  }, []);

  async function run(fn) {
    setError(null);
    setJob(null);
    try {
      setJob(await fn());
    } catch (err) {
      setError(err.message);
    }
  }

  function submitTranscribe(e) {
    e.preventDefault();
    if (audioFile) run(() => api.transcribeFile(audioFile, instrument));
  }

  function submitSynthesize(e) {
    e.preventDefault();
    if (sheetFile) run(() => api.synthesize(sheetFile, instrument));
  }

  const status = job?.status;
  const busy = status && !TERMINAL.includes(status);
  const canTranscribe = !!audioFile && !busy;

  const instrumentField = (label) => (
    <label className="field">
      <span className="field-label">{label}</span>
      <select value={instrument} onChange={(e) => setInstrument(e.target.value)}>
        {instruments.map((i) => (
          <option key={i.key} value={i.key}>
            {i.display_name}
          </option>
        ))}
      </select>
    </label>
  );

  function openFromLibrary(jobId) {
    api.job(jobId).then((j) => {
      setJob(j);
      setAppMode(j.kind === "synthesize" ? "synthesize" : "transcribe");
      setPage("studio");
    });
  }

  return (
    <div className="app">
      <header className="hero">
        <div className="hero-mark">𝄞</div>
        <div className="hero-text">
          <p className="eyebrow">Piano transcription &amp; practice</p>
          <h1>Manuscript</h1>
          <p className="hero-tagline">
            Recordings into sheet music, scores back into sound.
          </p>
        </div>
        <div className="hero-spacer" />
        <UserMenu
          user={user}
          onSignIn={() => setShowAuth(true)}
          onSignedOut={() => {
            setUser(null);
            setPage("studio");
          }}
        />
      </header>

      <nav className="pages">
        {PAGES.map(([key, label]) => (
          <button
            key={key}
            className={`page-tab ${page === key ? "active" : ""}`}
            aria-current={page === key ? "page" : undefined}
            onClick={() => setPage(key)}
          >
            {label}
          </button>
        ))}
      </nav>

      {/* Keyed on `page` so the blurb and the content below it fade in together
          when you switch tabs. */}
      <p className="page-intro" key={page}>
        {PAGES.find(([key]) => key === page)?.[2]}
      </p>

      {page === "library" && (
        <Library user={user} onOpen={openFromLibrary} onSignIn={() => setShowAuth(true)} />
      )}

      {page === "learn" && <Learn />}

      {page === "chords" && <Chords />}


      {page === "studio" && (
        <>
          <div className="mode-switch">
            <button
              className={`mode ${appMode === "transcribe" ? "active" : ""}`}
              onClick={() => {
                setAppMode("transcribe");
                setJob(null);
                setError(null);
              }}
            >
              Audio → Sheet
            </button>
            <button
              className={`mode ${appMode === "synthesize" ? "active" : ""}`}
              onClick={() => {
                setAppMode("synthesize");
                setJob(null);
                setError(null);
              }}
            >
              Sheet → Audio
            </button>
          </div>

          {appMode === "transcribe" ? (
            <form className="card panel" onSubmit={submitTranscribe}>

                <label className="dropzone">
                <input
                  type="file"
                  accept=".wav,.mp3,.flac,.ogg,.m4a,.aiff,audio/*"
                  onChange={(e) => setAudioFile(e.target.files?.[0] ?? null)}
                />
                <span className="dz-icon">⤒</span>
                <span className="dz-text">
                  {audioFile ? audioFile.name : "Choose an audio file"}
                </span>
                <span className="dz-hint">wav · mp3 · flac · m4a · ogg</span>
              </label>
              <p className="fine-print">
                Works best on a clean solo recording of one instrument. Pick the
                instrument below, then Transcribe — you’ll get a score you can
                play, click through and download.
              </p>

              <div className="controls">
                {instrumentField("Instrument")}
                <button className="primary" type="submit" disabled={!canTranscribe}>
                  {busy ? "Working…" : "Transcribe"}
                </button>
              </div>
            </form>
          ) : (
            <form className="card panel" onSubmit={submitSynthesize}>
              <label className="dropzone">
                <input
                  type="file"
                  accept={SHEET_ACCEPT}
                  onChange={(e) => setSheetFile(e.target.files?.[0] ?? null)}
                />
                <span className="dz-icon">♪</span>
                <span className="dz-text">
                  {sheetFile ? sheetFile.name : "Choose sheet music"}
                </span>
                <span className="dz-hint">MusicXML · MIDI · PDF · image</span>
              </label>
              <p className="fine-print">
                MusicXML/MIDI play back exactly. PDFs and images are read with
                optical music recognition — best-effort, and accuracy depends on
                the scan.
              </p>
              <div className="controls">
                {instrumentField("Play as")}
                <button className="primary" type="submit" disabled={!sheetFile || busy}>
                  {busy ? "Working…" : "Synthesize"}
                </button>
              </div>
            </form>
          )}

          {!user && job?.status === "done" && (
            <div className="banner banner-tip">
              <span className="banner-dot" />
              <div>
                <strong>Signed out — this won’t be saved.</strong>
                <span className="banner-sub">
                  <button className="link-btn inline" onClick={() => setShowAuth(true)}>
                    Sign in
                  </button>{" "}
                  to keep your work in a library.
                </span>
              </div>
            </div>
          )}

          {job && status !== "done" && (
            <div className={`banner banner-${status}`}>
              <span className="banner-dot" />
              <div>
                {status === "queued" && <strong>Queued…</strong>}
                {status === "running" && (
                  <>
                    <strong>
                      {appMode === "transcribe" ? "Transcribing…" : "Reading the score…"}
                    </strong>
                    <span className="banner-sub">This can take a moment.</span>
                  </>
                )}
                {status === "rejected" && (
                  <>
                    <strong>Couldn’t process this.</strong>
                    <span className="banner-sub">{job.error}</span>
                  </>
                )}
                {status === "failed" && (
                  <>
                    <strong>Something went wrong.</strong>
                    <span className="banner-sub">
                      {(job.error || "").split("\n")[0]}
                    </span>
                  </>
                )}
              </div>
            </div>
          )}

          {error && <div className="banner banner-failed">{error}</div>}

          {status === "done" && <ScoreResult job={job} />}
        </>
      )}

      {showAuth && (
        <AuthDialog
          googleEnabled={googleEnabled}
          onClose={() => setShowAuth(false)}
          onSignedIn={(u) => {
            setUser(u);
            setShowAuth(false);
          }}
        />
      )}

      <Poller job={job} setJob={setJob} />
    </div>
  );
}

// Polls a non-terminal job until it settles.
function Poller({ job, setJob }) {
  useEffect(() => {
    if (!job || TERMINAL.includes(job.status)) return;
    const timer = setInterval(async () => {
      try {
        setJob(await api.job(job.job_id));
      } catch {
        /* keep polling */
      }
    }, 1500);
    return () => clearInterval(timer);
  }, [job, setJob]);
  return null;
}
