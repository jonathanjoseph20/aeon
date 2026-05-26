from pathlib import Path

import yaml


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


def normalize_feed_urls(entry):
    feed_urls = entry.get("feed_url") or entry.get("feed_urls") or []

    if isinstance(feed_urls, str):
        feed_urls = [feed_urls]

    return [normalize_text(url) for url in feed_urls if normalize_text(url)]


def normalize_source_type(value, fallback=""):
    source_type = normalize_text(value or fallback).lower()

    if source_type in {"newsletters", "newsletter_email", "email"}:
        return "newsletter"

    if source_type in {"pdfs", "document"}:
        return "pdf"

    return source_type


def normalize_source_entry(entry, source_type_hint=""):
    source_type = normalize_source_type(entry.get("source_type"), source_type_hint)
    feed_urls = normalize_feed_urls(entry)
    source_name = (
        entry.get("source_name")
        or entry.get("name")
        or entry.get("handle")
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
            "watchlist_boost": normalize_int(entry.get("watchlist_boost"), 0),
            "promotion_threshold_override": (
                normalize_int(threshold_override, 0)
                if threshold_override not in (None, "")
                else None
            ),
            "digest_enabled": normalize_bool(entry.get("digest_enabled"), True),
            "alert_enabled": normalize_bool(entry.get("alert_enabled"), True),
            "handle": normalize_handle(entry.get("handle") or entry.get("source_handle")),
            "gmail_label": normalize_text(entry.get("gmail_label")),
            "source_domain": normalize_text(entry.get("source_domain")),
            "source_url": normalize_text(entry.get("source_url")),
        }
    )

    if "importance_score" in entry:
        normalized["importance_score"] = normalize_int(entry.get("importance_score"), 1)

    return normalized


def iter_source_entries(config):
    if config.get("sources"):
        for entry in config.get("sources") or []:
            if isinstance(entry, dict):
                yield normalize_source_entry(entry)
        return

    for section in ("twitter", "newsletters", "pdf", "pdfs"):
        for entry in config.get(section, []) or []:
            if isinstance(entry, dict):
                yield normalize_source_entry(entry, section)


def load_source_entries(sources_path=Path("config/sources.yml")):
    config = load_yaml(sources_path)
    return list(iter_source_entries(config))


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
