#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
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

const [, , targetUrl, outputPath, screenshotPath] = process.argv;

if (!targetUrl || !outputPath || !screenshotPath) {
  console.error("usage: run_source_visual_audit.mjs <url> <output-path> <screenshot-path>");
  process.exit(1);
}

const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || process.env.LIGHTHOUSE_CHROME_PATH || "/usr/bin/chromium",
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});

function clamp(value, min = 0, max = 100) {
  return Math.max(min, Math.min(max, value));
}

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });
  await page.goto(targetUrl, { waitUntil: "networkidle", timeout: 120000 });
  await page.screenshot({ path: screenshotPath, fullPage: false });

  const payload = await page.evaluate(() => {
    const GENERIC_FONTS = new Set([
      "arial",
      "helvetica",
      "sans-serif",
      "system-ui",
      "-apple-system",
      "blinkmacsystemfont",
      "segoe ui",
      "times new roman",
      "georgia",
      "serif",
    ]);

    function visible(el) {
      if (!(el instanceof Element)) return false;
      const style = window.getComputedStyle(el);
      if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity || "1") < 0.05) {
        return false;
      }
      const rect = el.getBoundingClientRect();
      return rect.width > 4 && rect.height > 4;
    }

    function parseColor(input) {
      const match = String(input || "").match(/rgba?\(([^)]+)\)/i);
      if (!match) return null;
      const parts = match[1].split(",").map((part) => Number(part.trim()));
      if (parts.length < 3) return null;
      return {
        r: parts[0],
        g: parts[1],
        b: parts[2],
        a: parts.length >= 4 ? parts[3] : 1,
      };
    }

    function luminance(color) {
      const convert = (channel) => {
        const value = channel / 255;
        return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * convert(color.r) + 0.7152 * convert(color.g) + 0.0722 * convert(color.b);
    }

    function contrastRatio(foreground, background) {
      const l1 = luminance(foreground);
      const l2 = luminance(background);
      const lighter = Math.max(l1, l2);
      const darker = Math.min(l1, l2);
      return (lighter + 0.05) / (darker + 0.05);
    }

    function findBackground(el) {
      let current = el;
      while (current && current instanceof Element) {
        const color = parseColor(window.getComputedStyle(current).backgroundColor);
        if (color && color.a > 0.85) return color;
        current = current.parentElement;
      }
      return { r: 255, g: 255, b: 255, a: 1 };
    }

    function normalizeFont(fontFamily) {
      const first = String(fontFamily || "")
        .split(",")[0]
        .replace(/["']/g, "")
        .trim()
        .toLowerCase();
      return first || "unknown";
    }

    const viewportHeight = window.innerHeight;
    const firstViewportEls = Array.from(document.querySelectorAll("body *")).filter((el) => {
      if (!visible(el)) return false;
      const rect = el.getBoundingClientRect();
      return rect.top < viewportHeight && rect.bottom > 0;
    });

    const headings = Array.from(document.querySelectorAll("h1, h2, h3")).filter(visible);
    const paragraphs = Array.from(document.querySelectorAll("p, li")).filter(visible);
    const images = Array.from(document.querySelectorAll("img, svg, picture")).filter(visible);
    const sections = Array.from(document.querySelectorAll("section, main > div, body > div")).filter((el) => {
      if (!visible(el)) return false;
      const rect = el.getBoundingClientRect();
      return rect.width > 280 && rect.height > 120;
    });
    const buttons = Array.from(
      document.querySelectorAll("button, a[role='button'], a[class*='button'], a[class*='btn']")
    ).filter(visible);

    const headingSizes = headings.map((el) => Number.parseFloat(window.getComputedStyle(el).fontSize || "0"));
    const paragraphSizes = paragraphs.map((el) => Number.parseFloat(window.getComputedStyle(el).fontSize || "0"));
    const lineHeights = paragraphs
      .map((el) => {
        const style = window.getComputedStyle(el);
        const fontSize = Number.parseFloat(style.fontSize || "16");
        const lineHeight = Number.parseFloat(style.lineHeight || "0");
        if (!Number.isFinite(lineHeight) || lineHeight <= 0) return 1.4;
        return lineHeight / fontSize;
      })
      .filter((value) => Number.isFinite(value));

    const fontFamilies = new Set(
      [...headings, ...paragraphs, ...buttons]
        .slice(0, 40)
        .map((el) => normalizeFont(window.getComputedStyle(el).fontFamily))
        .filter(Boolean)
    );
    const nonGenericFonts = Array.from(fontFamilies).filter((font) => !GENERIC_FONTS.has(font));

    const bodyContrastSamples = paragraphs.slice(0, 12).map((el) => {
      const style = window.getComputedStyle(el);
      const fg = parseColor(style.color);
      const bg = findBackground(el);
      return fg && bg ? contrastRatio(fg, bg) : 21;
    });
    const bodyContrastFailures = bodyContrastSamples.filter((value) => value < 4.5).length;

    const buttonContrastSamples = buttons.slice(0, 8).map((el) => {
      const style = window.getComputedStyle(el);
      const fg = parseColor(style.color);
      const bg = parseColor(style.backgroundColor) || findBackground(el);
      return fg && bg ? contrastRatio(fg, bg) : 21;
    });
    const weakButtonContrast = buttonContrastSamples.filter((value) => value < 3.5).length;

    const firstViewportWords = firstViewportEls
      .map((el) => (el.textContent || "").trim())
      .join(" ")
      .split(/\s+/)
      .filter(Boolean).length;

    const firstViewportLinks = firstViewportEls.filter((el) => el.tagName === "A").length;
    const firstViewportCtas = firstViewportEls.filter((el) => {
      const text = (el.textContent || "").trim().toLowerCase();
      return /(book|reserve|quote|contact|schedule|start|get started|call|visit|order|request)/.test(text);
    }).length;

    const heroHeading = headings.find((el) => {
      const rect = el.getBoundingClientRect();
      return el.tagName === "H1" && rect.top < viewportHeight * 0.75;
    });
    const heroHeadingSize = heroHeading
      ? Number.parseFloat(window.getComputedStyle(heroHeading).fontSize || "0")
      : 0;
    const heroMediaPresent = images.some((el) => {
      const rect = el.getBoundingClientRect();
      const area = rect.width * rect.height;
      return rect.top < viewportHeight && rect.bottom > 0 && area >= 100000;
    });

    const aboveFoldImageArea = images.reduce((sum, el) => {
      const rect = el.getBoundingClientRect();
      if (rect.top >= viewportHeight || rect.bottom <= 0) return sum;
      const clippedHeight = Math.min(rect.bottom, viewportHeight) - Math.max(rect.top, 0);
      return sum + Math.max(0, rect.width * clippedHeight);
    }, 0);
    const viewportArea = Math.max(1, window.innerWidth * viewportHeight);
    const aboveFoldImageCoverage = aboveFoldImageArea / viewportArea;

    let score = 50;
    const strongSignals = [];
    const weakSignals = [];

    if (heroHeadingSize >= 48) {
      score += 12;
      strongSignals.push("headline hierarchy is strong above the fold");
    } else if (heroHeadingSize >= 36) {
      score += 7;
    } else {
      score -= 10;
      weakSignals.push("hero heading lacks strong visual scale");
    }

    const medianParagraphSize = paragraphSizes.length
      ? paragraphSizes.sort((a, b) => a - b)[Math.floor(paragraphSizes.length / 2)]
      : 0;
    if (medianParagraphSize >= 15 && medianParagraphSize <= 19) {
      score += 8;
      strongSignals.push("body text sizing is readable");
    } else if (medianParagraphSize < 14) {
      score -= 10;
      weakSignals.push("body text appears undersized");
    } else if (medianParagraphSize > 20) {
      score -= 3;
    }

    const medianLineHeight = lineHeights.length
      ? lineHeights.sort((a, b) => a - b)[Math.floor(lineHeights.length / 2)]
      : 1.4;
    if (medianLineHeight >= 1.45) {
      score += 6;
    } else if (medianLineHeight < 1.3) {
      score -= 8;
      weakSignals.push("text rhythm looks tight");
    }

    if (fontFamilies.size >= 1 && fontFamilies.size <= 3) {
      score += 6;
      strongSignals.push("typography looks reasonably consistent");
    } else if (fontFamilies.size > 4) {
      score -= 8;
      weakSignals.push("too many font families are visible");
    }
    if (nonGenericFonts.length >= 1) {
      score += 3;
    } else {
      weakSignals.push("the site relies on generic typography");
    }

    if (firstViewportCtas >= 1) {
      score += 12;
      strongSignals.push("primary CTA presence is clear");
    } else {
      score -= 12;
      weakSignals.push("above-the-fold CTA presence is weak");
    }

    if (buttons.length >= 1 && buttons.length <= 6) {
      score += 5;
    } else if (buttons.length === 0) {
      score -= 8;
      weakSignals.push("interactive CTA styling is weak or absent");
    } else if (buttons.length > 8) {
      score -= 4;
      weakSignals.push("too many button-style actions compete for attention");
    }

    if (weakButtonContrast === 0 && buttonContrastSamples.length) {
      score += 5;
    } else if (weakButtonContrast >= 2) {
      score -= 8;
      weakSignals.push("button contrast looks weak");
    }

    if (heroMediaPresent) {
      score += 6;
      strongSignals.push("hero imagery or visual framing is present");
    } else {
      score -= 4;
      weakSignals.push("the page lacks strong above-the-fold visual framing");
    }

    if (aboveFoldImageCoverage >= 0.12 && aboveFoldImageCoverage <= 0.7) {
      score += 5;
    } else if (aboveFoldImageCoverage < 0.05) {
      score -= 6;
      weakSignals.push("above-the-fold imagery is sparse");
    }

    if (sections.length >= 4) {
      score += 8;
      strongSignals.push("page rhythm is broken into multiple visual sections");
    } else if (sections.length <= 1) {
      score -= 8;
      weakSignals.push("the page feels structurally shallow");
    }

    if (bodyContrastFailures === 0 && bodyContrastSamples.length) {
      score += 8;
      strongSignals.push("body text contrast looks healthy");
    } else if (bodyContrastFailures >= 3) {
      score -= 12;
      weakSignals.push("text contrast issues are visible");
    }

    if (firstViewportWords <= 140) {
      score += 4;
    } else if (firstViewportWords > 240) {
      score -= 8;
      weakSignals.push("the first viewport feels text-heavy");
    }

    if (firstViewportLinks > 18) {
      score -= 6;
      weakSignals.push("the first viewport feels cluttered with links");
    }

    if (images.length >= 3) {
      score += 4;
    } else if (images.length === 0) {
      score -= 6;
      weakSignals.push("the page has almost no visible imagery");
    }

    return {
      status: "ok",
      visualDesignScore: Math.round(clamp(score)),
      strongSignals: strongSignals.slice(0, 8),
      weakSignals: weakSignals.slice(0, 8),
      metrics: {
        heroHeadingSize: Math.round(heroHeadingSize),
        medianParagraphSize: Math.round(medianParagraphSize * 10) / 10,
        medianLineHeight: Math.round(medianLineHeight * 100) / 100,
        fontFamilyCount: fontFamilies.size,
        nonGenericFontCount: nonGenericFonts.length,
        firstViewportCtas,
        firstViewportWords,
        firstViewportLinks,
        buttonCount: buttons.length,
        weakButtonContrast,
        bodyContrastFailures,
        imageCount: images.length,
        sectionCount: sections.length,
        aboveFoldImageCoverage: Math.round(aboveFoldImageCoverage * 1000) / 1000,
      },
    };
  });

  payload.screenshot = screenshotPath;
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, JSON.stringify(payload, null, 2), "utf8");
  process.stdout.write(JSON.stringify(payload));
} finally {
  await browser.close();
}
