import { useState } from "react";
import { api } from "./api.js";

/** Sign-in / registration dialog. */
export function AuthDialog({ googleEnabled, onClose, onSignedIn }) {
  const [mode, setMode] = useState("login"); // login | register
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res =
        mode === "login"
          ? await api.login(email, password)
          : await api.register(email, password, name);
      onSignedIn(res.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>{mode === "login" ? "Welcome back" : "Create an account"}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <p className="footnote modal-intro">
          An account saves your transcriptions to a library. You can also use
          the studio without signing in.
        </p>

        {googleEnabled && (
          <>
            <a className="google-btn" href="/auth/google/login">
              <span className="g-mark">G</span> Continue with Google
            </a>
            <div className="divider">
              <span>or</span>
            </div>
          </>
        )}

        <form onSubmit={submit}>
          {mode === "register" && (
            <label className="field">
              <span className="field-label">Name</span>
              <input
                className="text-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
                autoComplete="name"
              />
            </label>
          )}
          <label className="field">
            <span className="field-label">Email</span>
            <input
              className="text-input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </label>
          <label className="field">
            <span className="field-label">Password</span>
            <input
              className="text-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
            />
            {mode === "register" && (
              <span className="hint">At least 8 characters.</span>
            )}
          </label>

          {error && <div className="form-error">{error}</div>}

          <button className="primary full" type="submit" disabled={busy}>
            {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <p className="switch-mode">
          {mode === "login" ? "New here? " : "Already have an account? "}
          <button
            className="link-btn inline"
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setError(null);
            }}
          >
            {mode === "login" ? "Create an account" : "Sign in"}
          </button>
        </p>
      </div>
    </div>
  );
}

/** Avatar + sign out, or a sign-in button. */
export function UserMenu({ user, onSignIn, onSignedOut }) {
  const [open, setOpen] = useState(false);

  if (!user) {
    return (
      <button className="ghost-btn" onClick={onSignIn}>
        Sign in
      </button>
    );
  }

  const initial = (user.name || user.email || "?").trim()[0].toUpperCase();

  return (
    <div className="user-menu">
      <button className="avatar-btn" onClick={() => setOpen((o) => !o)}>
        {user.picture ? (
          <img className="avatar" src={user.picture} alt="" referrerPolicy="no-referrer" />
        ) : (
          <span className="avatar avatar-initial">{initial}</span>
        )}
        <span className="user-name">{user.name}</span>
      </button>
      {open && (
        <div className="menu-pop card">
          <div className="menu-email">{user.email}</div>
          <button
            className="menu-item"
            onClick={async () => {
              await api.logout();
              setOpen(false);
              onSignedOut();
            }}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
