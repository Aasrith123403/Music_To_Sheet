// Thin API helper. Cookies carry the session, so every call must send them.
async function request(path, options = {}) {
  const res = await fetch(path, { credentials: "same-origin", ...options });
  const isJson = (res.headers.get("content-type") || "").includes("json");
  const body = isJson ? await res.json().catch(() => ({})) : null;
  if (!res.ok) {
    throw new Error(body?.detail || `Request failed (${res.status})`);
  }
  return body;
}

export const api = {
  me: () => request("/auth/me"),
  register: (email, password, name) =>
    request("/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, name }),
    }),
  login: (email, password) =>
    request("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
  logout: () => request("/auth/logout", { method: "POST" }),

  instruments: () => request("/instruments"),
  job: (id) => request(`/jobs/${id}`),
  library: () => request("/library"),
  rename: (id, title) =>
    request(`/jobs/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  remove: (id) => request(`/jobs/${id}`, { method: "DELETE" }),

  transcribeFile: (file, instrument) => {
    const body = new FormData();
    body.append("file", file);
    body.append("instrument", instrument);
    return request("/jobs", { method: "POST", body });
  },
  synthesize: (file, instrument) => {
    const body = new FormData();
    body.append("file", file);
    body.append("instrument", instrument);
    return request("/synthesize", { method: "POST", body });
  },

  quiz: (clef, count) => request(`/learn/quiz?clef=${clef}&count=${count}`),
  keys: () => request("/learn/keys"),
  scale: (tonic, type) => request(`/learn/scales?tonic=${tonic}&type=${type}`),
  scaleTypes: () => request("/learn/scale-types"),
  practice: () => request("/learn/practice"),

  chordQualities: () => request("/chords/qualities"),
  buildChord: (root, quality, inversion = 0, octave = 4) =>
    request("/chords/build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root, quality, inversion, octave }),
    }),
  identifyChord: (pitches) =>
    request("/chords/identify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pitches }),
    }),
  chordKey: (tonic, mode) => request(`/chords/key?tonic=${tonic}&mode=${mode}`),

};

