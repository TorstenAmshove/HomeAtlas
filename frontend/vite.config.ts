import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  define: {
    // Release version, passed as Docker build arg by release.yml. The build context has no .git
    // directory; local and PR builds show "dev".
    __APP_VERSION__: JSON.stringify(process.env.VITE_APP_VERSION?.trim() || "dev"),
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": { target: process.env.VITE_BACKEND_URL || "http://localhost:8000", changeOrigin: true },
    },
  },
});
