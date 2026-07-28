import { useEffect, useState } from "react";
import { api } from "./api.js";

function Difficulty({ value }) {
  if (!value) return null;
  return (
    <span className={`diff diff-${value.level}`} title={value.reasons.join(", ")}>
      {"●".repeat(value.level)}
      <span className="diff-dim">{"●".repeat(5 - value.level)}</span>
      <em>{value.label}</em>
    </span>
  );
}

export default function Library({ user, onOpen, onSignIn }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("recent");

  async function load() {
    try {
      const res = await api.library();
      setItems(res.items);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    if (user) load();
    else setItems([]);
  }, [user]);

  if (!user) {
    return (
      <div className="card empty-state">
        <h2>Your library</h2>
        <p>
          Sign in to keep your transcriptions, scans and arrangements in one
          place — with the key, tempo and difficulty of each.
        </p>
        <button className="primary" onClick={onSignIn}>
          Sign in
        </button>
      </div>
    );
  }

  if (error) return <div className="banner banner-failed">{error}</div>;
  if (items === null) return <div className="card empty-state">Loading…</div>;

  if (!items.length) {
    return (
      <div className="card empty-state">
        <h2>Nothing saved yet</h2>
        <p>Anything you transcribe while signed in shows up here.</p>
      </div>
    );
  }

  const shown = items
    .filter((it) => {
      const q = query.trim().toLowerCase();
      if (!q) return true;
      return [it.title, it.key, it.instrument]
        .filter(Boolean)
        .some((f) => String(f).toLowerCase().includes(q));
    })
    .sort((a, b) => {
      if (sort === "title") return (a.title || "").localeCompare(b.title || "");
      if (sort === "difficulty")
        return (b.difficulty?.level || 0) - (a.difficulty?.level || 0);
      return (b.created_at || 0) - (a.created_at || 0);
    });

  return (
    <div className="library">
      <div className="library-bar">
        <input
          className="text-input"
          placeholder="Search by name, key or instrument…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="recent">Newest first</option>
          <option value="title">By name</option>
          <option value="difficulty">Hardest first</option>
        </select>
      </div>

      {!shown.length && (
        <div className="card empty-state">
          <p>Nothing matches “{query}”.</p>
        </div>
      )}

      {shown.map((it) => (
        <div className="card lib-item" key={it.job_id}>
          <div className="lib-main" onClick={() => onOpen(it.job_id)}>
            <div className="lib-title-row">
              {editing === it.job_id ? (
                <input
                  className="text-input"
                  value={draft}
                  autoFocus
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={async (e) => {
                    if (e.key === "Enter") {
                      await api.rename(it.job_id, draft);
                      setEditing(null);
                      load();
                    }
                    if (e.key === "Escape") setEditing(null);
                  }}
                />
              ) : (
                <h3>{it.title}</h3>
              )}
              <span className={`kind kind-${it.kind}`}>
                {it.kind === "synthesize" ? "Sheet → Audio" : "Audio → Sheet"}
              </span>
            </div>
            <div className="lib-meta">
              {it.key && <span>{it.key}</span>}
              {it.tempo_bpm && <span>{it.tempo_bpm} BPM</span>}
              {it.duration_hms && <span>{it.duration_hms}</span>}
              {it.instrument && <span className="cap">{it.instrument}</span>}
              {it.status !== "done" && <span className="warn">{it.status}</span>}
            </div>
            <Difficulty value={it.difficulty} />
          </div>
          <div className="lib-actions">
            <button
              className="link-btn"
              onClick={() => {
                setEditing(it.job_id);
                setDraft(it.title || "");
              }}
            >
              Rename
            </button>
            <button
              className="link-btn danger"
              onClick={async () => {
                if (!confirm(`Delete "${it.title}"? This can't be undone.`)) return;
                await api.remove(it.job_id);
                load();
              }}
            >
              Delete
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
