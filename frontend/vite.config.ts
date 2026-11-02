import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The production build is emitted into the backend so FastAPI serves the SPA
// from the same origin (no CORS, works offline once loaded). During dev, API
// and WebSocket calls are proxied to the backend on :8000.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../backend/app/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true, ws: true },
      "/health": "http://localhost:8000",
      "/metrics": "http://localhost:8000",
    },
  },
});
