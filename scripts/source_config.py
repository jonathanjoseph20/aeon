from pathlib import Path
import re
from urllib.parse import urlparse

import yaml


DEFAULT_TWITTER_PROVIDER = "nitter"
DEFAULT_TWITTER_PROVIDER_TEMPLATES = {
    "rsshub": "https://rsshub.app/twitter/user/{handle}",
    "nitter": "https://nitter.net/{handle}/rss",
}

PRIORITY_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
}


def load_yaml(path):
    path = Path(path)

    if not path.exists():
        return {}

    with path.open("r") as handle:
        return yaml.safe_load(handle) or {}


def normalize_text(value):
    return str(value or "").strip()


def normalize_handle(value):
    return normalize_text(value).lstrip("@").lower()


def normalize_provider_name(value):
    return normalize_text(value).lower()


def looks_like_twitter_handle(value):
    handle = normalize_handle(value)

    if not handle:
        return False

    return bool(re.fullmatch(r"[a-z0-9_]{1,15}", handle))


def normalize_twitter_provider_entry(name, entry):
    provider_name = normalize_provider_name(name or entry.get("name") or entry.get("type"))
    provider_type = normalize_provider_name(
        entry.get("type")
        or entry.get("provider_type")
        or provider_name
    )
    url_template = normalize_text(
        entry.get("url_template")
        or entry.get("template")
        or entry.get("feed_url_template")
    )

    if not url_template:
        url_template = DEFAULT_TWITTER_PROVIDER_TEMPLATES.get(provider_type, "")

    if not url_template:
        url_template = DEFAULT_TWITTER_PROVIDER_TEMPLATES.get(provider_name, "")

    return {
        "name": provider_name,
        "type": provider_type or provider_name,
        "url_template": url_template,
    }


def load_twitter_provider_config(providers_path=Path("config/providers.yml")):
    config = load_yaml(providers_path)

    if not isinstance(config, dict):
        config = {}

    twitter_config = config.get("twitter")

    if not isinstance(twitter_config, dict):
        twitter_config = {}

    default_provider = normalize_provider_name(
        twitter_config.get("default_provider")
        or config.get("default_provider")
        or DEFAULT_TWITTER_PROVIDER
    )

    providers_raw = twitter_config.get("providers")

    if providers_raw is None:
        providers_raw = config.get("providers") or {}

    providers = {}

    if isinstance(providers_raw, dict):
        provider_items = providers_raw.items()
    elif isinstance(providers_raw, list):
        provider_items = []

        for entry in providers_raw:
            if not isinstance(entry, dict):
                continue

            provider_name = (
                entry.get("name")
                or entry.get("provider")
                or entry.get("id")
                or entry.get("type")
            )

            if provider_name:
                provider_items.append((provider_name, entry))
    else:
        provider_items = []

    for provider_name, entry in provider_items:
        normalized = normalize_twitter_provider_entry(provider_name, entry)

        if normalized["name"]:
            providers[normalized["name"]] = normalized

    for provider_name, url_template in DEFAULT_TWITTER_PROVIDER_TEMPLATES.items():
        providers.setdefault(
            provider_name,
            {
                "name": provider_name,
                "type": provider_name,
                "url_template": url_template,
            },
        )

    if default_provider not in providers:
        default_provider = DEFAULT_TWITTER_PROVIDER

    return {
        "default_provider": default_provider,
        "providers": providers,
    }


def resolve_twitter_provider(provider=None, providers_config=None):
    providers_config = providers_config or load_twitter_provider_config()
    providers = providers_config.get("providers") or {}

    if isinstance(provider, dict):
        resolved = normalize_twitter_provider_entry(
            provider.get("name") or provider.get("type") or providers_config.get("default_provider"),
            provider,
        )

        if resolved["url_template"]:
            return resolved

        return providers.get(providers_config.get("default_provider")) or providers.get(DEFAULT_TWITTER_PROVIDER)

    provider_name = normalize_provider_name(
        provider or providers_config.get("default_provider") or DEFAULT_TWITTER_PROVIDER
    )

    if provider_name in providers:
        return providers[provider_name]

    if provider_name in DEFAULT_TWITTER_PROVIDER_TEMPLATES:
        return {
            "name": provider_name,
            "type": provider_name,
            "url_template": DEFAULT_TWITTER_PROVIDER_TEMPLATES[provider_name],
        }

    return providers.get(providers_config.get("default_provider")) or providers.get(DEFAULT_TWITTER_PROVIDER)


def build_twitter_feed_url(handle, provider=None):
    normalized_handle = normalize_handle(handle)

    if not normalized_handle:
        return ""

    provider_config = resolve_twitter_provider(provider)

    if not provider_config:
        return ""

    url_template = normalize_text(provider_config.get("url_template"))

    if not url_template:
        return ""

    try:
        return url_template.format(handle=normalized_handle)
    except Exception:
        return ""


def extract_twitter_handle_from_url(value):
    raw_value = normalize_text(value)

    if not raw_value:
        return ""

    parsed = urlparse(raw_value)

    if parsed.scheme not in {"http", "https"}:
        return ""

    host = parsed.netloc.lower()

    if host.startswith("www."):
        host = host[4:]

    if host not in {"x.com", "twitter.com"}:
        return ""

    path_parts = [part for part in parsed.path.split("/") if part]

    if len(path_parts) != 1:
        return ""

    handle = normalize_handle(path_parts[0])

    if not handle or handle in {"home", "intent", "search", "explore", "i"}:
        return ""

    return handle


def normalize_twitter_handle(entry):
    explicit_handle = normalize_handle(
        entry.get("twitter_handle")
        or entry.get("handle")
        or entry.get("source_handle")
    )

    if explicit_handle:
        return explicit_handle

    source_name_handle = normalize_handle(entry.get("source_name"))

    if looks_like_twitter_handle(source_name_handle):
        return source_name_handle

    handle_from_profile_url = extract_twitter_handle_from_url(entry.get("feed_url"))

    if handle_from_profile_url:
        return handle_from_profile_url

    return ""


def resolve_twitter_feed_details(entry, providers_config=None, source_type_hint=""):
    source_type = normalize_source_type(entry.get("source_type"), source_type_hint)
    providers_config = providers_config or load_twitter_provider_config()

    if source_type != "twitter":
        feed_urls = entry.get("feed_url") or entry.get("feed_urls") or []

        if isinstance(feed_urls, str):
            feed_urls = [feed_urls]

        return [normalize_text(url) for url in feed_urls if normalize_text(url)], "", ""

    provider_name = normalize_provider_name(
        entry.get("twitter_feed_provider")
        or entry.get("feed_provider")
        or entry.get("provider")
    )
    provider_config = resolve_twitter_provider(provider_name or None, providers_config)
    provider_label = (
        provider_config.get("name")
        or provider_config.get("type")
        or provider_name
        or providers_config.get("default_provider")
        or DEFAULT_TWITTER_PROVIDER
    )

    feed_urls = entry.get("feed_url") or entry.get("feed_urls") or []

    if isinstance(feed_urls, str):
        feed_urls = [feed_urls]

    normalized_feed_urls = []
    saw_explicit_feed_url = False
    saw_profile_feed_url = False

    for url in feed_urls:
        normalized_url = normalize_text(url)

        if not normalized_url:
            continue

        profile_handle = extract_twitter_handle_from_url(normalized_url)

        if profile_handle:
            normalized_url = build_twitter_feed_url(
                normalize_twitter_handle(entry) or profile_handle,
                provider_config,
            )
            saw_profile_feed_url = True
        else:
            saw_explicit_feed_url = True

        if normalized_url:
            normalized_feed_urls.append(normalized_url)

    if normalized_feed_urls:
        if saw_profile_feed_url:
            return normalized_feed_urls, provider_label, normalized_feed_urls[0]

        if saw_explicit_feed_url:
            return normalized_feed_urls, "explicit", normalized_feed_urls[0]

    handle = normalize_twitter_handle(entry)

    if handle:
        generated_url = build_twitter_feed_url(handle, provider_config)

        if generated_url:
            return [generated_url], provider_label, generated_url

    return [], "", ""


def normalize_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_bool(value, default=True):
    if value in (None, ""):
        return default

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() not in {"false", "0", "no", "off"}


def normalize_list(value):
    if value in (None, ""):
        return []

    if isinstance(value, str):
        values = [value]
    else:
        values = list(value)

    normalized = []
    seen = set()

    for entry in values:
        text = normalize_text(entry)

        if not text or text in seen:
            continue

        seen.add(text)
        normalized.append(text)

    return normalized


def normalize_feed_urls(entry, providers_config=None, source_type_hint=""):
    feed_urls, _, _ = resolve_twitter_feed_details(entry, providers_config, source_type_hint)
    return feed_urls


def normalize_source_type(value, fallback=""):
    source_type = normalize_text(value or fallback).lower()

    if source_type in {"newsletters", "newsletter_email", "email"}:
        return "newsletter"

    if source_type in {"pdfs", "document"}:
        return "pdf"

    return source_type


def normalize_source_entry(entry, source_type_hint="", providers_config=None):
    source_type = normalize_source_type(entry.get("source_type"), source_type_hint)
    feed_urls, feed_provider, generated_feed_url = resolve_twitter_feed_details(
        entry,
        providers_config,
        source_type,
    )

    handle = normalize_twitter_handle(entry) if source_type == "twitter" else normalize_handle(
        entry.get("handle")
        or entry.get("source_handle")
    )
    source_name = (
        entry.get("source_name")
        or entry.get("name")
        or handle
        or entry.get("gmail_label")
        or entry.get("source_url")
        or (feed_urls[0] if feed_urls else "")
        or "Unknown"
    )
    priority = normalize_text(entry.get("priority") or "low").lower()
    default_verticals = normalize_list(
        entry.get("default_verticals") or entry.get("verticals")
    )
    threshold_override = entry.get("promotion_threshold_override")

    normalized = dict(entry)
    normalized.update(
        {
            "source_name": source_name,
            "source_type": source_type,
            "priority": priority,
            "default_verticals": default_verticals,
            "feed_urls": feed_urls,
            "feed_url": feed_urls[0] if feed_urls else normalize_text(entry.get("feed_url")),
            "generated_feed_url": generated_feed_url,
            "feed_provider": feed_provider,
            "watchlist_boost": normalize_int(entry.get("watchlist_boost"), 0),
            "promotion_threshold_override": (
                normalize_int(threshold_override, 0)
                if threshold_override not in (None, "")
                else None
            ),
            "digest_enabled": normalize_bool(entry.get("digest_enabled"), True),
            "alert_enabled": normalize_bool(entry.get("alert_enabled"), True),
            "handle": handle,
            "twitter_handle": normalize_handle(entry.get("twitter_handle") or handle),
            "twitter_feed_provider": feed_provider,
            "gmail_label": normalize_text(entry.get("gmail_label")),
            "source_domain": normalize_text(entry.get("source_domain")),
            "source_url": normalize_text(entry.get("source_url")),
        }
    )

    if "importance_score" in entry:
        normalized["importance_score"] = normalize_int(entry.get("importance_score"), 1)

    return normalized


def iter_source_entries(config, providers_config=None):
    if config.get("sources"):
        for entry in config.get("sources") or []:
            if isinstance(entry, dict):
                yield normalize_source_entry(entry, providers_config=providers_config)
        return

    for section in ("twitter", "newsletters", "pdf", "pdfs"):
        for entry in config.get(section, []) or []:
            if isinstance(entry, dict):
                yield normalize_source_entry(entry, section, providers_config)


def load_source_entries(
    sources_path=Path("config/sources.yml"),
    providers_path=Path("config/providers.yml"),
):
    config = load_yaml(sources_path)
    providers_config = load_twitter_provider_config(providers_path)
    return list(iter_source_entries(config, providers_config))


def _matches_source_type(item_source_type, entry_source_type):
    if not entry_source_type:
        return False

    if item_source_type == entry_source_type:
        return True

    if item_source_type.startswith("email") and entry_source_type == "newsletter":
        return True

    if item_source_type == "newsletter" and entry_source_type.startswith("email"):
        return True

    return False


def source_match_score(raw_item, entry):
    score = 0
    item_source_type = normalize_source_type(raw_item.get("source_type"))
    entry_source_type = normalize_source_type(entry.get("source_type"))

    if item_source_type and entry_source_type and _matches_source_type(
        item_source_type,
        entry_source_type,
    ):
        score += 4

    item_handle = normalize_handle(
        raw_item.get("source_handle")
        or raw_item.get("author_handle")
        or raw_item.get("handle")
        or raw_item.get("username")
    )

    if item_handle and entry.get("handle") and item_handle == entry["handle"]:
        score += 5

    item_name = normalize_text(raw_item.get("source_name")).lower()
    if item_name and normalize_text(entry.get("source_name")).lower() == item_name:
        score += 3

    item_label = normalize_text(raw_item.get("gmail_label")).lower()
    if item_label and normalize_text(entry.get("gmail_label")).lower() == item_label:
        score += 5

    item_domain = normalize_text(raw_item.get("source_domain")).lower()
    entry_domain = normalize_text(entry.get("source_domain")).lower()
    sender = normalize_text(raw_item.get("sender")).lower()

    if item_domain and entry_domain:
        if item_domain == entry_domain or item_domain.endswith(entry_domain):
            score += 4
        elif entry_domain in item_domain:
            score += 3
        elif entry_domain in sender:
            score += 3

    if item_source_type == "twitter":
        source_url = normalize_text(raw_item.get("source_url") or raw_item.get("tweet_url"))
        feed_urls = entry.get("feed_urls") or ([] if not entry.get("feed_url") else [entry.get("feed_url")])

        if source_url and any(source_url == normalize_text(url) for url in feed_urls):
            score += 4

    if item_source_type == "pdf":
        item_url = normalize_text(raw_item.get("source_url") or raw_item.get("source_file"))

        if item_url and normalize_text(entry.get("source_url")).lower() == item_url.lower():
            score += 4

        if item_url and normalize_text(entry.get("source_name")).lower() in item_url.lower():
            score += 2

    if item_source_type in {"email_manual", "newsletter", "pdf"}:
        if normalize_text(raw_item.get("source_name")).lower() == normalize_text(entry.get("source_name")).lower():
            score += 2

    return score


def find_source_entry(raw_item, source_entries):
    best_entry = None
    best_score = 0

    for entry in source_entries:
        score = source_match_score(raw_item, entry)

        if score > best_score:
            best_score = score
            best_entry = entry

    return best_entry if best_score > 0 else None


def merge_priority(base_priority, configured_priority):
    base_value = PRIORITY_ORDER.get(normalize_text(base_priority).lower(), 0)
    configured_value = PRIORITY_ORDER.get(normalize_text(configured_priority).lower(), 0)

    for priority, value in PRIORITY_ORDER.items():
        if value == max(base_value, configured_value):
            return priority

    return normalize_text(base_priority or configured_priority or "low").lower()


def priority_score_boost(priority):
    return {
        "high": 2,
        "medium": 1,
        "low": 0,
    }.get(normalize_text(priority).lower(), 0)


def merge_verticals(*vertical_groups):
    merged = []
    seen = set()

    for group in vertical_groups:
        for vertical in normalize_list(group):
            if vertical in seen:
                continue

            seen.add(vertical)
            merged.append(vertical)

    return merged


def is_enabled(record, field_name, default=True):
    return normalize_bool(record.get(field_name), default)
