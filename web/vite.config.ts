import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the UI calls /api/..., and Vite forwards it to the FastAPI server, so no CORS setup is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.STMTAI_API ?? "http://127.0.0.1:8000", rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
  test: { environment: "node" },
});
