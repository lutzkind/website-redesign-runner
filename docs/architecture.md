# Architecture

## Flow

1. Receive job request.
2. Capture source homepage HTML.
3. Build prompt from markdown skills plus request data.
4. Run OpenCode in the job directory.
5. Publish `dist/` as a static preview.
6. Send success or failure notification email.

## Why markdown skills

The skill files are editable without changing the runner code. This keeps prompt iteration fast and version-controlled.
