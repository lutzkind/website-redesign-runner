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
- `GET /preview/<client-slug>/`

## Request shape

```json
{
  "website_url": "https://example.com",
  "design_references": ["https://stripe.com", "https://linear.app"],
  "client_slug": "example-client",
  "industry": "restaurant",
  "brand_notes": "Premium editorial redesign with stronger reservation CTA.",
  "enabled_skills": [
    "website-audit",
    "design-direction",
    "layout-composer",
    "frontend-art-direction",
    "design-critic"
  ],
  "extra_instructions": "Keep the menu visible above the fold on desktop.",
  "notify_email": "lutz.kind96@gmail.com",
  "dry_run": false
}
```

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

## Local run

```bash
docker compose up --build
```

## Coolify

This repo is intended to deploy in Coolify using the **Docker Compose** build pack so the app can keep source control while still mounting server-side auth/config for OpenCode and Gmail.
