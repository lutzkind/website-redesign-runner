# Website Redesign Runner

Git-backed runner for AI website redesign jobs.

## What it does

- accepts redesign jobs over HTTP
- captures the source homepage HTML
- builds a prompt from adjustable markdown skills
- runs `opencode run`
- publishes static previews
- sends success or failure emails

## Endpoints

- `GET /health`
- `GET /skills`
- `GET /skills/<name>`
- `POST /jobs`
- `GET /jobs/<job_id>`
- `GET /jobs/<job_id>/prompt`
- `GET /jobs/<job_id>/prompt-parts`
- `GET /jobs/<job_id>/artifacts/<path>`
- `GET /preview/<client-slug>/`

## Request shape

```json
{
  "website_url": "https://example.com",
  "design_references": [
    {
      "url": "https://stripe.com",
      "focus": "Use the typography scale, dark/light contrast, and premium section spacing."
    },
    {
      "url": "https://linear.app",
      "focus": "Borrow the product storytelling rhythm and restrained motion direction."
    }
  ],
  "client_slug": "example-client",
  "industry": "restaurant",
  "generator_profile": "quality",
  "reference_limit": 1,
  "image_strategy": "hybrid",
  "reuse_source_images": true,
  "allow_external_images": true,
  "impeccable_critique": true,
  "impeccable_autofix": true,
  "design_goal": "Luxury redesign that feels expensive and cinematic.",
  "brand_notes": "Premium editorial redesign with stronger reservation CTA.",
  "enabled_skills": [
    "website-audit",
    "design-direction",
    "layout-composer",
    "frontend-art-direction",
    "design-critic"
  ],
  "extra_instructions": "Keep the menu visible above the fold on desktop.",
  "prompt_append": "Push harder on atmospheric imagery and premium materials.",
  "notify_email": "lutz.kind96@gmail.com",
  "dry_run": false
}
```

## Iteration controls

The runner now exposes the main operator levers directly in the job payload:

- `generator_profile`: `lean`, `balanced`, or `quality`
- `reference_limit`: clamp references per run without editing the reference list
- `image_strategy`: `source-only`, `source-first`, `hybrid`, or `stock-first`
- `reuse_source_images`: whether to keep using source imagery when it is good enough
- `allow_external_images`: whether the model may upgrade weak photography with external/editorial imagery
- `impeccable_critique`: run the Impeccable detector on generated `dist/`
- `impeccable_autofix`: if Impeccable finds issues, run a short targeted refinement pass
- `source_expansion_mode`: `strict`, `balanced`, or `aggressive`
- `search_enrichment`: enable or disable external search fallback
- `search_budget`: max number of external enrichment results to merge
- `design_goal`: short statement of the intended creative outcome
- `prompt_append`: last-mile operator note appended into the prompt controls

For prompt inspection:

- `GET /jobs/<job_id>/prompt` returns the final prompt string
- `GET /jobs/<job_id>/prompt-parts` returns the structured prompt sections used to build it
- `GET /jobs/<job_id>/artifacts/prompt.metrics.json` exposes a per-part token estimate and audit suggestions
- `GET /jobs/<job_id>/artifacts/<path>` exposes generated screenshots, analysis JSON, and logs for operator review

This is enough to iterate without a dashboard at first. A dashboard becomes useful once you want saved presets, prompt/version history, and one-click reruns.

## Skill system

Prompt behavior is controlled by markdown files.

- bundled defaults live in `skills/` inside the repo
- on first boot the runner copies them into `/data/skills`
- top-level skills define cross-industry behavior
- `/data/skills/industry/*.md` adds domain-specific rules
- job payloads can override `industry`, `enabled_skills`, and `extra_instructions`

This makes the design system tunable without changing Python code:

- edit the persistent files under `runner-data/skills/` on the Coolify host
- inspect the active versions through `GET /skills` and `GET /skills/<name>`
- keep the repo defaults as the versioned baseline

## Analysis pipeline

- the runner uses Firecrawl to scrape the source site into markdown + HTML
- it also scrapes the first few reference sites so the prompt includes their actual structure and tone, not just their URLs
- each reference can include a `focus` field describing what the model should borrow from that site
- the runner now captures desktop and mobile screenshots for the source site and references, then derives a visual brief from those images
- each reference now gets a stronger visual brief: palette cues, brightness/contrast, saturation, section rhythm, image density, and mood signals
- each reference now also gets a CSS/DOM-driven `reference_blueprint` with typography roles, spacing scales, component patterns, and composition hints that are fed into the first generation pass
- the runner extracts source and reference asset candidates so the model can reuse logos/photos when helpful instead of returning imageless redesigns
- the runner scores source completeness and, when needed, uses Firecrawl search to enrich weak websites with external business context
- the runner writes `/jobs/<job_id>/source/analysis/business-profile.json` so prompts can use compact structured facts instead of raw scrape dumps
- screenshot and visual-analysis artifacts are stored per job under `/data/jobs/<job_id>/source/analysis/`
- the first generation pass now receives explicit anti-pattern guardrails inspired by `impeccable` before any post-generation critique runs
- the runner now writes `/jobs/<job_id>/prompt.metrics.json` so you can see estimated token spend by prompt section
- after generation, the runner can run `impeccable detect --json dist/` and optionally launch a compact repair pass against only the generated preview files
- if Firecrawl is unavailable for the source site, the runner falls back to a direct HTML fetch so jobs still run
- for Docker/Coolify deploys, set `WEBSITE_REDESIGN_FIRECRAWL_URL` to the reachable Firecrawl endpoint from inside the container

## Model policy

- the runner refuses to start with any `openrouter/*` model path
- default deployment model is `deepseek/deepseek-v4-flash`
- configure `WEBSITE_REDESIGN_MODEL` to a non-OpenRouter OpenCode model only
- DeepSeek prompt caching is automatic at the API layer; the runner keeps stable prompt sections first so repeated jobs and agent turns are more cache-friendly

## Local run

```bash
docker compose up --build
```

## Coolify

This repo is intended to deploy in Coolify using the **Docker Compose** build pack so the app can keep source control while still mounting server-side auth/config for OpenCode and Gmail.
