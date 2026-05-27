# Configuring Sources

`config/sources.yml` is the source registry AEON uses for downstream scoring and filtering.
It lets you tune source priority, default verticals, watchlist boosts, Hermes promotion thresholds, and whether a source can appear in the digest or alert queue.
Twitter feed URL generation is controlled by `config/providers.yml`.

## Common Fields

- `source_name`: Human-readable name used in the digest and promotion outputs.
- `source_type`: One of `newsletter`, `pdf`, or `twitter`.
- `priority`: `low`, `medium`, or `high`. Higher-priority sources get a scoring boost during classification.
- `default_verticals`: Vertical priors that AEON should attach to items from this source.
- `feed_url`: Optional RSS or Atom URL for Twitter feed ingestion. Plain `x.com` or `twitter.com` profile URLs are accepted as convenience input and normalized through the configured Twitter provider. If a Twitter source omits `feed_url`, AEON builds a URL from the active provider and handle.
- `twitter_handle`: Optional explicit Twitter handle field. AEON treats this the same as `handle`.
- `twitter_feed_provider`: Optional per-source provider override such as `rsshub`, `nitter`, or `custom`.
- `watchlist_boost`: Extra score to add when the item matches a watchlist entity.
- `promotion_threshold_override`: Per-source Hermes promotion threshold.
- `digest_enabled`: Set `false` to keep the source out of the daily digest.
- `alert_enabled`: Set `false` to keep the source out of alert candidate extraction.

## Add a Newsletter

Use `source_type: newsletter` and point the entry at the sender domain or Gmail label you already ingest.

```yaml
sources:
  - source_name: Bankless
    source_type: newsletter
    gmail_label: Research/DeFi
    source_domain: banklesshq.com
    priority: high
    default_verticals: [DeFi]
    watchlist_boost: 2
    promotion_threshold_override: 7
    digest_enabled: true
    alert_enabled: true
```

If AEON already learns the sender in `data/metadata/email_sources.json`, keep that file in sync so Gmail ingestion stamps the same source name and defaults.

## Add a PDF Source

Use `source_type: pdf` and make sure the ingested PDF record uses the same `source_name`.
`scripts/ingestion/ingest_pdf.py` already accepts `--source-name`, `--priority`, `--importance-score`, and `--vertical` flags.

```yaml
sources:
  - source_name: Macro PDF Brief
    source_type: pdf
    priority: medium
    default_verticals: [Macro]
    watchlist_boost: 1
    promotion_threshold_override: 5
    digest_enabled: false
    alert_enabled: false
```

## Add a Twitter Feed

Use `source_type: twitter` and include a handle. AEON will generate a provider URL automatically when `feed_url` is omitted.

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

AEON will resolve that source to:

```text
https://nitter.net/aaronjmars/rss
```

If you need a different proxy, a self-hosted RSSHub instance, or a non-RSSHub feed, update `config/providers.yml` or set `twitter_feed_provider` on the source entry. Plain `x.com` and `twitter.com` profile URLs are accepted as convenience input and normalized through the active provider.

Example provider registry:

```yaml
twitter:
  default_provider: nitter
  providers:
    rsshub:
      type: rsshub
      url_template: https://rsshub.app/twitter/user/{handle}
    nitter:
      type: nitter
      url_template: https://nitter.net/{handle}/rss
    custom:
      type: custom
      url_template: https://example.invalid/twitter/{handle}.xml
```

Then run the feed fetcher:

```bash
python3 scripts/ingestion/fetch_twitter.py --feeds
```

## Operational Notes

- `priority` changes the scoring baseline during classification.
- `promotion_threshold_override` is honored when AEON decides whether to promote an item to Hermes.
- `digest_enabled` and `alert_enabled` are evaluated downstream, so turning them off keeps the source in the intake log without surfacing it in those outputs.
- Provider availability is external to AEON, so feed success depends on the configured endpoint staying reachable and continuing to return valid RSS or Atom XML.
