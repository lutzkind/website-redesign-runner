#!/usr/bin/env node
import { execSync } from "node:child_process";

let globalNpmRoot = "";
try {
  globalNpmRoot = execSync("npm root -g", { encoding: "utf-8" }).trim();
} catch {}

const playwrightImportCandidates = Array.from(
  new Set(
    [
      "playwright",
      process.env.PLAYWRIGHT_MODULE_PATH,
      globalNpmRoot ? `${globalNpmRoot}/playwright/index.mjs` : "",
      "/usr/local/lib/node_modules/playwright/index.mjs",
    ].filter(Boolean),
  ),
);

let playwright = null;
let lastImportError = null;

for (const candidate of playwrightImportCandidates) {
  try {
    playwright = await import(candidate);
    break;
  } catch (error) {
    lastImportError = error;
  }
}

if (!playwright) {
  console.error("Unable to import Playwright from known locations.");
  if (lastImportError) console.error(String(lastImportError));
  process.exit(1);
}

const { chromium, devices } = playwright;

const [, , url, outputPath, deviceName = "Desktop Chrome"] = process.argv;

if (!url || !outputPath) {
  console.error("usage: capture_screenshot.mjs <url> <outputPath> [deviceName]");
  process.exit(1);
}

const browser = await chromium.launch({
  headless: true,
  args: ["--no-sandbox", "--disable-setuid-sandbox"],
});

try {
  const device = devices[deviceName] || devices["Desktop Chrome"];
  const context = await browser.newContext({
    ...device,
    locale: "en-US",
    colorScheme: "light",
  });
  const page = await context.newPage();
  await page.goto(url, { waitUntil: "networkidle", timeout: 45000 });
  await page.screenshot({ path: outputPath, fullPage: true, type: "png" });
  await context.close();
} finally {
  await browser.close();
}
