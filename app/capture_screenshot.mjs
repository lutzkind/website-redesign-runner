#!/usr/bin/env node
import { chromium, devices } from "playwright";

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
