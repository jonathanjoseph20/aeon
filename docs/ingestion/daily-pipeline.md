# AEON Daily Pipeline

AEON's daily pipeline is deterministic-first and avoids LLM calls by default. It ingests configured inputs, classifies them, adds summaries and clusters, extracts alert candidates, promotes high-signal items to Hermes append-only logs, builds the daily digest, and emits a Slack-safe outbox payload.

## Local Run

From the repo root:

```bash
python3 scripts/pipeline/run_local_pipeline.py
```

Optional inputs are picked up automatically when they are configured or present:

- Gmail intake runs when `credentials/token.json` or `credentials/gmail_credentials.json` exists.
- Local PDF ingestion runs when `data/intake/pdf/` contains `*.pdf` files.
- Twitter feed ingestion runs when `config/sources.yml` contains configured `feed_url` or `feed_urls` values.

Dry run the pipeline without executing any steps:

```bash
python3 scripts/pipeline/run_local_pipeline.py --dry-run
```

The pipeline writes these append-only outputs:

- `data/processed/intake_log.jsonl`
- `data/processed/topic_clusters.jsonl`
- `data/processed/alert_candidates.jsonl`
- `data/events/promote_to_hermes/YYYY-MM-DD.jsonl`
- `data/hermes/promoted/YYYY-MM-DD.jsonl`
- `data/processed/daily_digest.md`
- `data/outbox/slack/daily-intel-digest/YYYY-MM-DD.json`

The Slack payload is deterministic and is only written to the local outbox. AEON does not post to Slack directly during the daily pipeline.

To inspect the payload without writing the artifact, run:

```bash
python3 scripts/ingestion/build_slack_digest_payload.py --preview
```

Raw intake data stays out of git because the intake folders are ignored.

## GitHub Actions

The scheduled workflow lives in [`.github/workflows/daily-intel-digest.yml`](../../.github/workflows/daily-intel-digest.yml).

It supports both:

- `schedule` for the daily run
- `workflow_dispatch` for manual execution

The workflow restores Gmail secrets when they are provided, then runs the same local pipeline script. Twitter feed failures are logged by the ingestion script and do not fail the job.

The workflow does not call Hermes APIs and does not post to Slack directly.
It does produce the Slack-safe outbox payload artifact so it can be inspected or forwarded later by an operator.
