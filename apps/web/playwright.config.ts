import { defineConfig, devices } from "@playwright/test";
import { existsSync } from "node:fs";

/**
 * The preinstalled Chromium in this environment does not match the build
 * Playwright 1.62 expects, so point at it explicitly when it is there and fall
 * back to Playwright's own download everywhere else.
 */
const PREINSTALLED = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const executablePath = existsSync(PREINSTALLED) ? PREINSTALLED : undefined;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.SANI_WEB_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: { executablePath },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1600, height: 950 } } }],
});
