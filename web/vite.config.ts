import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 3000,
    proxy: {
      "/api": "http://localhost:8000",
      "/auth": "http://localhost:8000",
      "/v1": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
  },
});
