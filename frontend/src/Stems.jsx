import { useEffect, useState } from "react";
import { api } from "./api.js";

const TERMINAL = ["done", "failed", "rejected"];

const STEM_LABELS = {
  vocals: "Vocals",
  drums: "Drums",
  bass: "Bass",
  piano: "Piano",
  guitar: "Guitar",
  other: "Other",
};

export default function Stems({ user, onSignIn }) {
  const [models, setModels] = useState([]);
  const [available, setAvailable] = useState(true);
  const [model, setModel] = useState("htdemucs_6s");
  const [file, setFile] = useState(null);
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.stemModels()
      .then((d) => {
        setModels(d.models);
        setAvailable(d.available);
        setModel(d.default);
      })
      .catch(() => setAvailable(false));
  }, []);

  // Poll until the separation finishes.
  useEffect(() => {
    if (!job || TERMINAL.includes(job.status)) return;
    const timer = setInterval(async () => {
      try {
        setJob(await api.job(job.job_id));
      } catch {
        /* keep polling */
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [job]);

  async function submit(e) {
    e.preventDefault();
    if (!file) return;
    setError(null);
    setJob(null);
    try {
      setJob(await api.separate(file, model));
    } catch (err) {
      setError(err.message);
    }
  }

  const status = job?.status;
  const busy = status && !TERMINAL.includes(status);
  const stems = job?.analysis?.stems || [];
  const selected = models.find((m) => m.key === model);

  if (!available) {
    return (
      <div className="card empty-state">
        <h2>Stem separation isn’t installed</h2>
        <p>
          This feature needs Demucs. Install it with{" "}
          <code>pip install demucs</code> and restart the server.
        </p>
      </div>
    );
  }

  return (
    <>
      <form className="card panel" onSubmit={submit}>
        <label className="dropzone">
          <input
            type="file"
            accept=".wav,.mp3,.flac,.ogg,.m4a,.aiff,audio/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <span className="dz-icon">⑂</span>
          <span className="dz-text">{file ? file.name : "Choose a track to split"}</span>
          <span className="dz-hint">wav · mp3 · flac · m4a · ogg</span>
        </label>

        <p className="fine-print">
          Separation runs locally and is slow — roughly the length of the track
          on this machine, longer for the 6-stem model. Use it on music you have
          the right to sample.
        </p>

        <div className="controls">
          <label className="field">
            <span className="field-label">Model</span>
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {models.map((m) => (
                <option key={m.key} value={m.key}>{m.label}</option>
              ))}
            </select>
          </label>
          <button className="primary" type="submit" disabled={!file || busy}>
            {busy ? "Separating…" : "Split into stems"}
          </button>
        </div>
        {selected && <p className="footnote">{selected.note}</p>}
      </form>

      {!user && status === "done" && (
        <div className="banner banner-tip">
          <span className="banner-dot" />
          <div>
            <strong>Signed out — these stems won’t be saved.</strong>
            <span className="banner-sub">
              <button className="link-btn inline" onClick={onSignIn}>Sign in</button>{" "}
              to keep them in your library.
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
                <strong>Separating the track…</strong>
                <span className="banner-sub">
                  This takes a while — the model processes the whole file.
                </span>
              </>
            )}
            {status === "rejected" && (
              <>
                <strong>Couldn’t separate this.</strong>
                <span className="banner-sub">{job.error}</span>
              </>
            )}
            {status === "failed" && (
              <>
                <strong>Something went wrong.</strong>
                <span className="banner-sub">{(job.error || "").split("\n")[0]}</span>
              </>
            )}
          </div>
        </div>
      )}

      {error && <div className="banner banner-failed">{error}</div>}

      {status === "done" && stems.length > 0 && (
        <div className="card stems-card">
          <div className="section-head">
            <span>Stems</span>
          </div>
          <p className="footnote stems-note">
            Each part isolated from the mix. Demucs always emits every stem, so
            ones the track doesn’t contain come back silent — those are marked.
          </p>
          {stems.map((s) => (
            <div className={`stem ${s.silent ? "silent" : ""}`} key={s.name}>
              <div className="stem-head">
                <span className="stem-name">{STEM_LABELS[s.name] || s.name}</span>
                {s.silent ? (
                  <span className="stem-tag">nothing detected</span>
                ) : (
                  <span className="stem-meta">
                    peak {s.peak} · rms {s.rms}
                  </span>
                )}
                <a
                  className="link-btn"
                  href={`/jobs/${job.job_id}/stems/${s.name}`}
                  download={`${s.name}.wav`}
                >
                  ↓ WAV
                </a>
              </div>
              {!s.silent && (
                <audio
                  className="audio-player"
                  controls
                  preload="none"
                  src={`/jobs/${job.job_id}/stems/${s.name}`}
                />
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
