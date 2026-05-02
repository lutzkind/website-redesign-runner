# Architecture

## Flow

1. Receive job request.
2. Capture source homepage HTML.
3. Build prompt from markdown skills plus request data.
4. Run OpenCode in the job directory.
5. Publish `dist/` as a static preview.
6. Send success or failure notification email.

## Prospect qualification flow

1. `n8n` reads lead rows from NocoDB.
2. `n8n` calls `POST /qualify` for each website.
3. The runner reuses the same Firecrawl/source analysis pipeline.
4. The runner returns a scored assessment: `target`, `review`, or `skip`.
5. `n8n` writes the result back to NocoDB and routes only `target` leads into outreach.

## Why markdown skills

The skill files are editable without changing the runner code. This keeps prompt iteration fast and version-controlled.
