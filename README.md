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
  "client_slug": "example-client",
  "industry": "restaurant",
  "design_family": "editorial-luxury",
  "generator_profile": "quality",
  "image_strategy": "hybrid",
  "reuse_source_images": true,
  "allow_external_images": true,
  "seo_critique": true,
  "seo_autofix": true,
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

- `design_family`: optional override for the internal art-direction family
- `generator_profile`: `lean`, `balanced`, or `quality`
- `image_strategy`: `source-only`, `source-first`, `hybrid`, or `stock-first`
- `reuse_source_images`: whether to keep using source imagery when it is good enough
- `allow_external_images`: whether the model may upgrade weak photography with external/editorial imagery
- `seo_critique`: run the built-in SEO audit on generated `dist/`
- `seo_autofix`: if the SEO audit finds issues, run a short targeted SEO refinement pass before `impeccable`
- `impeccable_critique`: run the Impeccable detector on generated `dist/`
- `impeccable_autofix`: if Impeccable finds issues, run a short targeted refinement pass
- `source_expansion_mode`: `strict`, `balanced`, or `aggressive`
- `search_enrichment`: enable or disable external search fallback
- `search_budget`: max number of external enrichment results to merge
- `design_goal`: short statement of the intended creative outcome
- `prompt_append`: last-mile operator note appended into the prompt controls
- the runner now hard-requires a real location module near the footer with address, hours, phone, and a map/directions link

For prompt inspection:

- `GET /jobs/<job_id>/prompt` returns the final prompt string
- `GET /jobs/<job_id>/prompt-parts` returns the structured prompt sections used to build it
- `GET /jobs/<job_id>/artifacts/prompt.metrics.json` exposes a per-part token estimate and audit suggestions
- `GET /jobs/<job_id>/artifacts/<path>` exposes generated analysis JSON and logs for operator review

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
- it extracts source asset candidates so the model can reuse logos/photos when helpful instead of returning imageless redesigns
- the runner scores source completeness and, when needed, uses Firecrawl search to enrich weak websites with external business context
- the runner writes `/jobs/<job_id>/source/analysis/business-profile.json` so prompts can use compact structured facts instead of raw scrape dumps
- the runner selects an internal design family and writes `/jobs/<job_id>/source/analysis/design-engine.json`
- the runner generates a bespoke concept blueprint and writes `/jobs/<job_id>/source/analysis/concept-blueprint.json`
- the runner generates an SEO blueprint and writes `/jobs/<job_id>/source/analysis/seo-blueprint.json`
- the first generation pass now receives explicit anti-pattern guardrails inspired by `impeccable` before any post-generation critique runs
- the first generation pass also receives explicit SEO requirements: title, description, canonical, Open Graph, Twitter card, heading structure, alt text, JSON-LD, and footer/location consistency
- after generation, the runner writes `/jobs/<job_id>/seo-audit.json` and can run a compact SEO repair pass before `impeccable`
- the runner now writes `/jobs/<job_id>/prompt.metrics.json` so you can see estimated token spend by prompt section
- after generation, the runner can run `impeccable detect --json dist/` and optionally launch a compact repair pass against only the generated preview files
- if Firecrawl is unavailable for the source site, the runner falls back to a direct HTML fetch so jobs still run
- for Docker/Coolify deploys, set `WEBSITE_REDESIGN_FIRECRAWL_URL` to the reachable Firecrawl endpoint from inside the container

## Internal design families

The runner no longer depends on external reference websites. It selects from an internal art-direction family library and generates a concept blueprint for the first pass.

Available families:

- `editorial-luxury`
- `warm-hospitality`
- `cinematic-bold`
- `crisp-trust`
- `craftsman-premium`
- `modern-approachable`

The selector infers a family from the industry, design goal, brand notes, and source content unless you override it with `design_family`.

Restaurant note:

- diner / breakfast / family-owned signals now bias toward `warm-hospitality`
- `editorial-luxury` should usually be reserved for genuinely upscale or nightlife-driven restaurant positioning

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
