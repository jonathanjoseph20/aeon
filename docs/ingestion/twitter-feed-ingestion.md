# Twitter/X Feed Ingestion

AEON can ingest Twitter/X content from RSS or Atom feeds without using the paid X API.
This keeps ingestion deterministic-first and avoids adding any LLM dependency.

## Quick Setup

1. Open `config/sources.yml`.
2. Add a `feed_url` next to any Twitter handle you want AEON to fetch.
3. Use a feed URL you are allowed to access, such as an RSS or Atom endpoint provided by a compliant feed source.
4. Keep the existing `handle` so AEON can attach the right source metadata.

Example:

```yaml
twitter:
  - handle: aaronjmars
    name: Aaron J. Mars
    feed_url: https://example.com/feeds/aaronjmars.xml
    priority: high
    importance_score: 6
```

## Run It

From the repo root:

```bash
python3 scripts/ingestion/fetch_twitter.py --feeds
```

That writes normalized JSONL items into `data/intake/twitter/`.

## Smoke Command

For a quick verification run:

```bash
bash scripts/ingestion/smoke_twitter_feeds.sh
```

## What AEON Writes

Feed items are normalized into the same tweet-shaped intake schema as manual JSONL ingestion:

- `source_type: twitter`
- `source_handle`
- `source_url`
- `content`
- `dedupe_hash`
- `item_id`

The downstream classify and digest pipeline can keep reading `data/intake/twitter/` unchanged.
