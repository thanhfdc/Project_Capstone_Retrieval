import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, proxy the API (uvicorn on :8000) so the browser sees one origin like in Docker.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://localhost:8000", "/media": "http://localhost:8000" },
  },
});
