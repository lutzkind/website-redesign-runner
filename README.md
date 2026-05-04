# Website Redesign Runner

Git-backed runner for AI website redesign jobs.

## What it does

- accepts redesign jobs over HTTP
- captures the source homepage HTML
- builds a prompt from adjustable markdown skills
- runs `opencode run`
- publishes static previews
- sends success or failure emails
- qualifies websites for outbound redesign prospecting

## Endpoints

- `GET /health`
- `GET /skills`
- `GET /skills/<name>`
- `POST /jobs`
- `GET /jobs/<job_id>`
- `GET /jobs/<job_id>/prompt`
- `GET /jobs/<job_id>/prompt-parts`
- `GET /jobs/<job_id>/artifacts/<path>`
- `POST /qualify`
- `GET /qualification-runs/<qualification_id>`
- `GET /preview/<client-slug>/`

## Request shape

```json
{
  "website_url": "https://example.com",
  "client_slug": "example-client",
  "industry": "restaurant",
  "run_mode": "prospect",
  "design_family": "editorial-luxury",
  "generator_profile": "lean",
  "image_strategy": "hybrid",
  "reuse_source_images": true,
  "allow_external_images": true,
  "content_critique": true,
  "content_autofix": false,
  "seo_critique": true,
  "seo_autofix": false,
  "impeccable_critique": false,
  "impeccable_autofix": false,
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

- `run_mode`: `prospect` or `refined`
- `design_family`: optional override for the internal art-direction family
- `generator_profile`: `lean`, `balanced`, or `quality`
- `image_strategy`: `source-only`, `source-first`, `hybrid`, or `stock-first`
- `reuse_source_images`: whether to keep using source imagery when it is good enough
- `allow_external_images`: whether the model may upgrade weak photography with external/editorial imagery
- `content_critique`: run the built-in content-integrity audit on generated `dist/`
- `content_autofix`: if the content audit finds issues, run a short targeted refinement pass before SEO / `impeccable`
- `seo_critique`: run the built-in SEO audit on generated `dist/`
- `seo_autofix`: if the SEO audit finds issues, run a short targeted SEO refinement pass before `impeccable`
- `lighthouse_critique`: run a Lighthouse-based SEO/performance/best-practices audit on generated `dist/`
- `lighthouse_autofix`: if Lighthouse finds issues, run a short targeted refinement pass before `impeccable`
- `axe_critique`: run an axe accessibility audit on generated `dist/`
- `axe_autofix`: if axe finds issues, run a short targeted accessibility refinement pass before `impeccable`
- `impeccable_critique`: run the Impeccable detector on generated `dist/`
- `impeccable_autofix`: if Impeccable finds issues, run a short targeted refinement pass
- `source_expansion_mode`: `strict`, `balanced`, or `aggressive`
- `search_enrichment`: enable or disable external search fallback
- `search_budget`: max number of external enrichment results to merge
- `design_goal`: short statement of the intended creative outcome
- `prompt_append`: last-mile operator note appended into the prompt controls
- the runner now hard-requires a real location module near the footer with address, hours, phone, and a map/directions link

Default operating modes:

- `prospect`: optimized for fast first drafts and lower token usage. Defaults to `generator_profile=lean`, `source_expansion_mode=strict`, `search_budget=2`, content and SEO audits on, all autofix passes off, and no Lighthouse/axe/Impeccable passes.
- `refined`: optimized for retained customers or second-pass upgrades. Defaults to `generator_profile=balanced`, `source_expansion_mode=balanced`, `search_budget=4`, content and SEO autofix on, plus Lighthouse, axe, and Impeccable critiques enabled.

The intent is to keep normal prospecting jobs under control and reserve the expensive audit/refinement stack for pages that are worth polishing further.

For prompt inspection:

- `GET /jobs/<job_id>/prompt` returns the final prompt string
- `GET /jobs/<job_id>/prompt-parts` returns the structured prompt sections used to build it
- `GET /jobs/<job_id>/artifacts/prompt.metrics.json` exposes a per-part token estimate and audit suggestions
- `GET /jobs/<job_id>/artifacts/<path>` exposes generated analysis JSON and logs for operator review

This is enough to iterate without a dashboard at first. A dashboard becomes useful once you want saved presets, prompt/version history, and one-click reruns.

## Lead qualification

Use `POST /qualify` as the scoring service behind an `n8n` lead workflow. `n8n` should:

1. read a batch of leads from NocoDB
2. loop over rows with a website
3. call the runner's `/qualify` endpoint
4. write `qualification_status`, scores, and reasons back to NocoDB
5. forward only `target` rows into your outreach workflow

An importable starter workflow is included at `workflows/scraper-leads-qualification.n8n.json`. It is prewired to the current NocoDB `Scraper Leads` table and expects the table's source URL column to be named `website`.

Example request:

```json
{
  "website_url": "https://example.com",
  "industry": "restaurant",
  "company_name": "Example Kitchen",
  "lead_id": "lead_123",
  "source_row_id": "245"
}
```

Response highlights:

- `assessment.qualification_status`: `target`, `review`, or `skip`
- `assessment.website_quality_score`: higher means the current site is stronger
- `assessment.redesign_opportunity_score`: higher means better redesign outreach target
- `assessment.weak_signals`: why the site looks weak
- `assessment.strong_signals`: why the site may already be good enough to skip
- `visual_audit.visualDesignScore`: browser-based visual design heuristic score for the live source site
- `source_lighthouse.scores`: live-site Lighthouse baseline used by the evaluator
- `source_axe.findings`: live-site accessibility violations used by the evaluator

Each qualification run is stored under `/data/qualification-runs/<id>/qualification.json` and exposed at `GET /qualification-runs/<id>`.

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
- the runner builds a MagicUI-inspired component vocabulary and writes `/jobs/<job_id>/source/analysis/component-blueprint.json`
- the runner generates a bespoke concept blueprint and writes `/jobs/<job_id>/source/analysis/concept-blueprint.json`
- the runner generates a content blueprint and writes `/jobs/<job_id>/source/analysis/content-blueprint.json`
- the runner generates an SEO blueprint and writes `/jobs/<job_id>/source/analysis/seo-blueprint.json`
- the first generation pass now receives concrete component patterns for hero/nav/CTA/gallery/footer plus industry subtype adaptations instead of relying only on abstract family prose
- the content planner now defines required sections and rewrite targets so the model rebuilds key business content like menus/services instead of just restyling source copy
- the first generation pass now receives explicit anti-pattern guardrails inspired by `impeccable` before any post-generation critique runs
- the first generation pass now also receives content-integrity constraints: rewrite the source, do not link back to the legacy site, rebuild critical content like menus/services inside the redesign, and never invent unsupported reviews or ratings
- after generation, the runner writes `/jobs/<job_id>/content-audit.json` and can run a compact content-integrity repair pass before SEO and `impeccable`
- the first generation pass also receives explicit SEO requirements: title, description, canonical, Open Graph, Twitter card, heading structure, alt text, JSON-LD, and footer/location consistency
- after generation, the runner writes `/jobs/<job_id>/seo-audit.json` and can run a compact SEO repair pass before `impeccable`
- after generation, the runner writes `/jobs/<job_id>/lighthouse-audit.json` and can run a compact Lighthouse-driven repair pass before `impeccable`
- after generation, the runner writes `/jobs/<job_id>/axe-audit.json` and can run a compact accessibility repair pass before `impeccable`
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

The family is no longer the only visual driver. Each family now expands into a MagicUI-inspired component blueprint:

- hero pattern
- nav pattern
- CTA pattern
- gallery pattern
- proof pattern
- footer/location pattern

This gives the first draft more concrete UI structure than the earlier prose-only family descriptions.

The runner now also uses a broader local-business niche matrix on top of the family layer. It can infer and adapt for subtypes such as:

- `restaurant-diner`
- `restaurant-cafe`
- `restaurant-bakery`
- `restaurant-pizzeria`
- `restaurant-upscale`
- `restaurant-bar`
- `trades-plumber`
- `trades-electrician`
- `trades-hvac`
- `trades-roofer`
- `trades-landscaper`
- `trades-pest-control`
- `service-cleaning`
- `service-auto-detailing`
- `care-dentist`
- `care-orthodontist`
- `care-medspa`
- `care-chiropractor`
- `care-vet`
- `trust-legal`
- `trust-accounting`
- `retail-florist`
- `retail-boutique`
- `retail-jewelry`
- `retail-furniture`
- `wellness-salon`
- `wellness-fitness`

This niche matrix affects:

- family selection
- schema type
- conversion priorities
- required sections
- rewrite targets
- component adaptations
- section flow

It is still not an exhaustive taxonomy for every possible local business, but it is materially more specific than the earlier broad buckets.

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
