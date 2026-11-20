import { defineConfig, devices } from "@playwright/test";

// Smoke test against an already running stack (CI: the freshly built frontend + backend images on
// the host network, see .github/workflows/build.yml). Nothing is started from here on purpose --
// the point is to exercise the real images, nginx config and uvicorn start included.
function browser() {
  return {
    ...devices["Desktop Chrome"],
    // Local runs only: lets a pre-installed Chromium stand in for `playwright install`.
    launchOptions: process.env.SMOKE_CHROMIUM_PATH ? { executablePath: process.env.SMOKE_CHROMIUM_PATH } : {},
  };
}

export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.ts",
  // The tests walk one fresh database through login -> MFA -> setup; they cannot run twice or in
  // parallel against the same backend, and a retry would hit an already-enrolled admin.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.SMOKE_BASE_URL || "http://127.0.0.1:8280",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  // Two projects so the order is fixed: gates-calm.spec.ts walks the redesigned gates with a second
  // admin that smoke.spec.ts creates at its end (one fresh backend, each walk enrolls its own user).
  projects: [
    { name: "smoke", testMatch: "smoke.spec.ts", use: browser() },
    { name: "gates-calm", testMatch: "gates-calm.spec.ts", dependencies: ["smoke"], use: browser() },
  ],
});
