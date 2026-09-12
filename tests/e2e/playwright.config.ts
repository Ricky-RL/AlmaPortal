import "dotenv/config";

import { defineConfig, devices } from "@playwright/test";

import { contract } from "./helpers/contract.js";

const resendWebServer = contract.resend.startStub
  ? [
      {
        command: "pnpm resend:stub",
        url: `${contract.resend.origin}/__health`,
        reuseExistingServer: !process.env.CI,
        timeout: 15_000,
      },
    ]
  : undefined;

export default defineConfig({
  testDir: "./specs",
  outputDir: "./test-results",
  globalSetup: "./global-setup.ts",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  timeout: 45_000,
  expect: {
    timeout: 8_000,
  },
  reporter: process.env.CI
    ? [["line"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: contract.webBaseUrl,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
  },
  ...(resendWebServer ? { webServer: resendWebServer } : {}),
  projects: [
    {
      name: "desktop-chromium",
      grepInvert: /@mobile/,
      use: {
        ...devices["Desktop Chrome"],
      },
    },
    {
      name: "mobile-chromium",
      grep: /@mobile/,
      use: {
        ...devices["Pixel 7"],
      },
    },
  ],
});
