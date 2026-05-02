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

const { default: lighthouse } = await importGlobal("lighthouse", "lighthouse/core/index.js");
const { launch } = await importGlobal("chrome-launcher", "chrome-launcher/dist/index.js");

const [, , targetUrl, outputPath] = process.argv;

if (!targetUrl || !outputPath) {
  console.error("usage: run_lighthouse_audit.mjs <url> <output-path>");
  process.exit(1);
}

const chrome = await launch({
  chromeFlags: ["--headless", "--no-sandbox", "--disable-dev-shm-usage"],
  chromePath: process.env.CHROME_PATH || process.env.LIGHTHOUSE_CHROME_PATH || "/usr/bin/chromium",
});

try {
  const result = await lighthouse(targetUrl, {
    port: chrome.port,
    output: "json",
    logLevel: "error",
    onlyCategories: ["performance", "accessibility", "best-practices", "seo"],
  });

  const reportJson = JSON.parse(result.report);
  const categories = reportJson.categories || {};
  const audits = reportJson.audits || {};
  const scores = {
    performance: Math.round((categories.performance?.score || 0) * 100),
    accessibility: Math.round((categories.accessibility?.score || 0) * 100),
    bestPractices: Math.round((categories["best-practices"]?.score || 0) * 100),
    seo: Math.round((categories.seo?.score || 0) * 100),
  };

  const ruleMap = [
    ["document-title", "high", "Title tag is weak or missing."],
    ["meta-description", "high", "Meta description is weak or missing."],
    ["http-status-code", "high", "Page returned a non-200 status during audit."],
    ["crawlable-anchors", "medium", "Some links may not be crawlable."],
    ["is-crawlable", "high", "Page may not be crawlable."],
    ["link-text", "medium", "Link text is weak or non-descriptive."],
    ["image-alt", "medium", "Images are missing alt text."],
    ["structured-data", "high", "Structured data is missing or invalid."],
    ["font-size", "medium", "Font sizing hurts readability."],
    ["uses-text-compression", "low", "Text compression is not enabled in preview context."],
    ["uses-responsive-images", "low", "Responsive image opportunities detected."],
    ["unused-javascript", "low", "Unused JavaScript detected."],
    ["render-blocking-resources", "medium", "Render-blocking resources slow first paint."],
    ["largest-contentful-paint", "medium", "Largest contentful paint is slower than ideal."],
  ];

  const findings = [];
  for (const [rule, severity, message] of ruleMap) {
    const audit = audits[rule];
    if (!audit) continue;
    if (audit.score === null || audit.score === undefined) continue;
    if (audit.score >= 0.9) continue;
    findings.push({
      rule,
      severity,
      message: audit.title || message,
      details: audit.description || "",
      displayValue: audit.displayValue || "",
      score: Math.round(audit.score * 100),
    });
  }

  for (const [name, score] of Object.entries(scores)) {
    if (score < 85) {
      findings.push({
        rule: `category-${name}`,
        severity: score < 70 ? "high" : "medium",
        message: `${name} score is ${score}, below target.`,
        score,
      });
    }
  }

  const payload = {
    status: findings.length ? "findings" : "clean",
    scores,
    findingsCount: findings.length,
    findings,
  };

  fs.writeFileSync(outputPath, JSON.stringify(payload, null, 2), "utf8");
  process.stdout.write(JSON.stringify(payload));
} finally {
  await chrome.kill();
}
