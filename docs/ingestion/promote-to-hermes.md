# Promote to Hermes

AEON can promote processed intake items into Hermes-oriented append-only logs without calling Hermes APIs or posting to Slack.

## Command

```bash
python3 scripts/ingestion/promote_to_hermes.py
```

## Outputs

- `data/events/promote_to_hermes/YYYY-MM-DD.jsonl`
- `data/hermes/promoted/YYYY-MM-DD.jsonl`

## Promotion Rules

An item is promoted when any of the following are true:

- `importance_score` is greater than the configured threshold
- `watchlist_hits` is present
- `signal_band` is `High Signal`

## Replay Safety

Promotion hashes are stable, so re-running the script skips items that were already materialized in either output stream.

## Dry Run

```bash
python3 scripts/ingestion/promote_to_hermes.py --dry-run
```

## Slack-Safe Payloads

If you want a Slack-ready notification envelope without sending anything, add:

```bash
python3 scripts/ingestion/promote_to_hermes.py --include-slack-payloads
```

The payload is attached to the structured event record only. Slack posting stays a separate step.

## Fixture Smoke Test

```bash
python3 -m unittest tests.test_promote_to_hermes
```
