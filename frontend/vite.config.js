import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API calls to the FastAPI backend so the frontend can use
// same-origin relative paths ("/jobs") in both dev and production.
//
// Listed as one regex rather than per-path entries: forgetting to add a new
// endpoint here makes the browser hit Vite instead of the API and get a 404
// that no backend test can catch (this happened with /synthesize).
const API_ROUTES = [
  "jobs",
  "instruments",
  "synthesize",
  "auth",
  "library",
  "learn",
  "chords",
];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      [`^/(${API_ROUTES.join("|")})(/.*)?$`]: {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
