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
4. Split In Batches
5. HTTP Request to `POST /qualify`
6. IF `assessment.qualification_status == "target"`
7. NocoDB update record with scores/reasons
8. Optional: pass only `target` rows into email enrichment or outreach

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
- `assessment.website_quality_score`
- `assessment.redesign_opportunity_score`
- `assessment.confidence`
- `assessment.summary`
- `assessment.weak_signals`
- `assessment.strong_signals`
- `qualification_id`

## Current scoring logic

The runner now scores seven buckets:

- content depth
- contact accessibility
- conversion clarity
- trust signals
- visual assets
- visual design
- site structure

`visual design` is evaluated with a browser-based audit of the live source site. It looks at headline scale, body text readability, CTA presence, button contrast, above-the-fold imagery, font consistency, and visible clutter rather than only the scraped HTML text.

Interpretation:

- `target`: weak enough to justify redesign outreach now
- `review`: mixed signals, worth human review
- `skip`: site already looks competent enough that redesign outreach is lower priority

## Practical first pass

Start strict. Only outreach `target` rows. Keep `review` rows in the table for later manual inspection, and ignore `skip`.

That gives you a cleaner first outbound motion and avoids wasting volume on businesses whose websites already clear a decent baseline.
