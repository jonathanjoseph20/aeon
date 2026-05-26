# Twitter/X Feed Ingestion

AEON can ingest Twitter/X content from RSS or Atom feeds without using the paid X API.
This keeps ingestion deterministic-first and avoids adding any LLM dependency.

## Quick Setup

1. Open `config/sources.yml`.
2. Add or update a `source_type: twitter` entry with `source_name` and `handle` or `twitter_handle`.
3. If you omit `feed_url`, AEON generates `https://rsshub.app/twitter/user/<handle>` automatically.
4. If you want a different proxy or a self-hosted RSSHub instance, set `feed_url` explicitly and AEON will preserve it.
5. Set `priority`, `default_verticals`, `watchlist_boost`, and `promotion_threshold_override` as needed.

Example:

```yaml
sources:
  - source_name: Aaron J. Mars
    source_type: twitter
    twitter_handle: aaronjmars
    priority: high
    default_verticals: [AI, Agents]
    watchlist_boost: 1
    promotion_threshold_override: 6
    digest_enabled: true
    alert_enabled: true
```

AEON resolves the feed to `https://rsshub.app/twitter/user/aaronjmars` unless you provide an explicit `feed_url`.

## Run It

From the repo root:

```bash
python3 scripts/ingestion/fetch_twitter.py --feeds
```

That writes normalized JSONL items into `data/intake/twitter/`.

## Validate a Feed URL

A feed URL is valid only if it returns a successful HTTP response, advertises an XML/RSS/Atom content type when available, and parses as well-formed feed XML.

Quick checks:

1. Run the fetcher against your configured sources.
2. Inspect `data/metadata/source_health.jsonl` for `status` and `error_reason`.
3. If a feed fails, verify the RSSHub endpoint is reachable and that it is still returning XML rather than an HTML error page or login wall.

Typical failure reasons include:

- `http_status_403`
- `http_status_404`
- `html_response`
- `malformed_xml`

RSSHub is the only deterministic Twitter feed source AEON auto-generates today, so if that service is down or changes its route shape, Twitter ingestion will fail until the feed URL is overridden or RSSHub recovers.

If you want a manual pre-check, compare the response headers and body before wiring the URL into `config/sources.yml`.

## Smoke Command

For a quick verification run:

```bash
bash scripts/ingestion/smoke_twitter_feeds.sh
```

## Fixture Tests

The deterministic fixture tests cover both manual JSONL ingestion and `--feeds` parsing without any network calls:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile scripts/ingestion/fetch_twitter.py
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
