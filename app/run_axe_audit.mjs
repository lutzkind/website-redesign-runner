#!/usr/bin/env node
import fs from "node:fs";
import { execSync } from "node:child_process";

let globalNpmRoot = "";
try {
  globalNpmRoot = execSync("npm root -g", { encoding: "utf-8" }).trim();
} catch {}

async function importGlobal(specifier, fallbackFile) {
  const candidates = Array.from(
    new Set(
      [
        specifier,
        globalNpmRoot ? `${globalNpmRoot}/${fallbackFile}` : "",
      ].filter(Boolean),
    ),
  );
  let lastError = null;
  for (const candidate of candidates) {
    try {
      return await import(candidate);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

const { chromium } = await importGlobal("playwright-core", "playwright-core/index.mjs");
const { default: axe } = await importGlobal("axe-core", "axe-core/axe.js");

const [, , targetUrl, outputPath] = process.argv;

if (!targetUrl || !outputPath) {
  console.error("usage: run_axe_audit.mjs <url> <output-path>");
  process.exit(1);
}

const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || process.env.LIGHTHOUSE_CHROME_PATH || "/usr/bin/chromium",
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
  await page.goto(targetUrl, { waitUntil: "networkidle", timeout: 120000 });
  await page.addScriptTag({ content: axe.source });
  const result = await page.evaluate(async () => {
    return await globalThis.axe.run(document, {
      runOnly: {
        type: "tag",
        values: ["wcag2a", "wcag2aa", "best-practice"],
      },
    });
  });

  const findings = (result.violations || []).map((violation) => ({
    rule: violation.id,
    severity: violation.impact || "unknown",
    message: violation.help,
    description: violation.description,
    nodes: violation.nodes.slice(0, 5).map((node) => ({
      target: node.target,
      html: node.html,
      failureSummary: node.failureSummary,
    })),
  }));

  const payload = {
    status: findings.length ? "findings" : "clean",
    findingsCount: findings.length,
    findings,
  };

  fs.writeFileSync(outputPath, JSON.stringify(payload, null, 2), "utf8");
  process.stdout.write(JSON.stringify(payload));
} finally {
  await browser.close();
}
