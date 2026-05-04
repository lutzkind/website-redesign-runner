# Lead Qualification Flow

## Recommended split

- `n8n` owns lead retrieval, batching, retries, and writing results back into NocoDB.
- `website-redesign-runner` owns website analysis and qualification scoring through `POST /qualify`.

This keeps the runner focused on website intelligence and keeps CRM/data orchestration inside `n8n`.

## Minimal NocoDB schema additions

Add these fields to your leads table:

- `website`
- `qualification_status`
- `website_quality_score`
- `redesign_opportunity_score`
- `qualification_confidence`
- `qualification_summary`
- `qualification_weak_signals`
- `qualification_strong_signals`
- `last_qualified_at`

## n8n node flow

1. Trigger
2. NocoDB list records
3. Filter rows where `website` exists and `qualification_status` is still empty
   also allow `failed` rows to retry after the cooldown window
4. Split In Batches
5. HTTP Request to `POST /qualify`
6. IF `assessment.qualification_status == "target"`
7. NocoDB update record with scores/reasons
8. Optional: pass only `target` rows into email enrichment or outreach, while routing `failed` rows into a retry or manual-review branch

The repo now includes an importable workflow at `workflows/scraper-leads-qualification.n8n.json`.
It is preconfigured for:

- NocoDB base `Luxeillum Leads` (`pc0fmz2i62ewg6n`)
- table `Scraper Leads` (`mswfxq541pe6khe`)
- source URL column `website`
- response writeback into the qualification fields already added to the table

After import, do two setup steps in `n8n`:

- attach your NocoDB credential to both NocoDB nodes
- set `WEBSITE_REDESIGN_RUNNER_URL` for the n8n instance if the runner is not reachable at `http://127.0.0.1:8000`

## Example `/qualify` call

```json
{
  "website_url": "https://example.com",
  "industry": "restaurant",
  "company_name": "Example Kitchen",
  "lead_id": "lead_123",
  "source_row_id": "245"
}
```

## Response fields to persist

- `assessment.qualification_status`
  possible values: `target`, `review`, `skip`, `failed`, `external_profile`
- `assessment.website_quality_score`
- `assessment.redesign_opportunity_score`
- `assessment.confidence`
- `assessment.summary`
- `assessment.weak_signals`
- `assessment.strong_signals`
- `qualification_id`

## Current scoring logic

The runner now scores ten buckets:

- content depth
- contact accessibility
- page coverage
- conversion clarity
- trust signals
- visual assets
- visual design
- technical health
- accessibility baseline
- site structure

`visual design` is evaluated with a browser-based audit of the live source site. It looks at headline scale, body text readability, CTA presence, button contrast, above-the-fold imagery, font consistency, and visible clutter rather than only the scraped HTML text.
`technical health` is based on a live Lighthouse run against the source site.
`accessibility baseline` is based on a live axe audit against the source site.

If one of the live audits is unavailable in the current runtime, the evaluator excludes that bucket from score normalization instead of treating it as a failing score.

Interpretation:

- `target`: weak enough to justify redesign outreach now
- `review`: mixed signals, worth human review
- `skip`: site already looks competent enough that redesign outreach is lower priority
- `failed`: the site could not be evaluated reliably because it was inaccessible, blocked, or challenge-gated
- `external_profile`: the lead points to a social/profile page rather than a standalone website

Additional suppression rules:

- obvious corporate location microsites are forced to `skip`
- branded hotel-chain property pages are forced to `skip`

## Practical first pass

Start strict. Only outreach `target` rows. Keep `review` rows in the table for later manual inspection, ignore `skip`, and treat `failed` as an evaluator failure state for retry or separate investigation.

Current workflow behavior:

- fresh rows with empty `qualification_status` are processed immediately
- `failed` rows can be retried after 24 hours
- `external_profile`, `review`, `skip`, and `target` rows are left alone unless you clear the status manually

That gives you a cleaner first outbound motion and avoids wasting volume on businesses whose websites already clear a decent baseline.
