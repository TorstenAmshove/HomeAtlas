import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";

const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    // Set by Docker build args (CI passes the commit and build time). The build context has no
    // .git directory, so these are computed by whoever triggers the build.
    __BUILD_SHA__: JSON.stringify(process.env.VITE_BUILD_SHA || "dev"),
    __BUILD_TIME__: JSON.stringify(process.env.VITE_BUILD_TIME || ""),
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": { target: process.env.VITE_BACKEND_URL || "http://localhost:8000", changeOrigin: true },
    },
  },
});
