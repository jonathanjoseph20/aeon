import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_SOURCE_REGISTRY_PATH = Path("config/source_registry.yml")
DEFAULT_INPUT_LOG_PATH = Path("data/processed/intake_log.jsonl")
DEFAULT_EVENT_DIR = Path("data/events/promote_to_hermes")
DEFAULT_HERMES_DIR = Path("data/hermes/promoted")
DEFAULT_OUTPUT_PATH = Path("data/processed/source_metrics.json")

_CONFIGURED_ENTITIES_CACHE = None


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_text(value):
    return str(value or "").strip()


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


def normalize_bool(value, default=True):
    if value in (None, ""):
        return default

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() not in {"false", "0", "no", "off"}


def clamp(value, low=0, high=100):
    return max(low, min(high, value))


def normalize_source_key(value):
    text = normalize_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def load_yaml(path):
    path = Path(path)

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_jsonl(path):
    path = Path(path)

    if not path.exists():
        return []

    records = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        record = json.loads(line)

        if isinstance(record, dict):
            records.append(record)

    return records


def iter_jsonl_paths(path):
    path = Path(path)

    if not path.exists():
        return []

    if path.is_dir():
        return sorted(path.glob("*.jsonl"))

    return [path]


def build_item_text(item):
    parts = [
        item.get("subject"),
        item.get("summary"),
        item.get("content_preview") or item.get("preview"),
        item.get("content"),
        item.get("raw_text"),
        item.get("source_name"),
        item.get("source_url"),
    ]

    cleaned = [normalize_text(part) for part in parts if normalize_text(part)]
    return " ".join(cleaned)


def narrative_signature(item):
    dedupe_hash = normalize_text(item.get("dedupe_hash"))

    if dedupe_hash:
        return dedupe_hash

    payload = build_item_text(item)

    if not payload:
        return ""

    return hashlib.sha256(payload.lower().encode("utf-8")).hexdigest()[:16]


def normalize_entities(value):
    if value in (None, ""):
        return []

    if isinstance(value, dict):
        value = list(value.values())

    if isinstance(value, str):
        values = [value]
    else:
        values = list(value)

    normalized = []
    seen = set()

    for entry in values:
        if isinstance(entry, dict):
            candidate = entry.get("entity_name") or entry.get("name") or entry.get("entity")
        else:
            candidate = entry

        text = normalize_text(candidate)

        if not text:
            continue

        key = text.lower()

        if key in seen:
            continue

        seen.add(key)
        normalized.append(text)

    return normalized


def load_configured_entities():
    global _CONFIGURED_ENTITIES_CACHE

    if _CONFIGURED_ENTITIES_CACHE is not None:
        return _CONFIGURED_ENTITIES_CACHE

    from scripts.ingestion.build_entity_summary import load_configured_entities as load_entities

    _CONFIGURED_ENTITIES_CACHE = load_entities()
    return _CONFIGURED_ENTITIES_CACHE


def item_entity_count(item):
    explicit_entities = item.get("entities")
    if explicit_entities is not None:
        return len(normalize_entities(explicit_entities))

    explicit_entity_keys = item.get("entity_keys")
    if explicit_entity_keys is not None:
        return len(normalize_entities(explicit_entity_keys))

    try:
        from scripts.ingestion.build_entity_summary import extract_entities
    except Exception:
        return 0

    text = build_item_text(item)

    if not text:
        return 0

    configured_entities = load_configured_entities()
    extracted = extract_entities(text, configured_entities=configured_entities)
    entity_keys = set()

    for entity in extracted:
        entity_key = normalize_text(entity.get("entity_key") or entity.get("entity_name")).lower()

        if entity_key:
            entity_keys.add(entity_key)

    return len(entity_keys)


def item_theme_count(item):
    return len(normalize_list(item.get("verticals") or item.get("themes") or []))


def load_source_registry(path=DEFAULT_SOURCE_REGISTRY_PATH):
    data = load_yaml(path)

    if isinstance(data, list):
        source_entries = data
    elif isinstance(data, dict):
        source_entries = data.get("sources") or data.get("source_registry") or []
    else:
        source_entries = []

    normalized = []

    for entry in source_entries:
        if not isinstance(entry, dict):
            continue

        source_id = normalize_text(entry.get("source_id") or entry.get("source_name"))
        source_key = normalize_source_key(source_id)

        if not source_key:
            continue

        normalized.append(
            {
                "source_id": source_id,
                "source_key": source_key,
                "platform": normalize_text(entry.get("platform") or "unknown").lower(),
                "category": normalize_text(entry.get("category") or "uncategorized").lower(),
                "verticals": normalize_list(entry.get("verticals")),
                "priority": normalize_text(entry.get("priority") or "low").lower(),
                "trust_score": clamp(safe_int(entry.get("trust_score"), 0), 0, 100),
                "noise_score": clamp(safe_int(entry.get("noise_score"), 0), 0, 100),
                "enabled": normalize_bool(entry.get("enabled"), True),
                "tags": normalize_list(entry.get("tags")),
            }
        )

    return sorted(normalized, key=lambda entry: entry["source_key"])


def load_items(path):
    return load_jsonl(path)


def item_identity(item, fallback_index):
    return normalize_text(
        item.get("item_id")
        or item.get("id")
        or item.get("source_item_id")
        or item.get("dedupe_hash")
        or item.get("source_id")
        or f"item-{fallback_index}"
    )


def item_source_key(item):
    return normalize_source_key(
        item.get("source_id")
        or item.get("source_name")
        or item.get("source")
        or item.get("source_handle")
        or item.get("author_handle")
        or item.get("handle")
        or item.get("username")
    )


def promotion_key(record):
    return normalize_text(
        record.get("promotion_hash")
        or record.get("event_id")
        or record.get("dedupe_hash")
        or record.get("item_id")
        or record.get("source_item_id")
    )


def build_item_lookup(items):
    lookup = {}

    for index, item in enumerate(items):
        item_key = item_identity(item, index)
        source_key = item_source_key(item)

        if item_key:
            lookup[item_key] = source_key

        dedupe_hash = normalize_text(item.get("dedupe_hash"))
        if dedupe_hash:
            lookup[dedupe_hash] = source_key

    return lookup


def build_promotion_index(event_dir, hermes_dir, item_lookup):
    promotions_by_source = defaultdict(set)

    for folder in (event_dir, hermes_dir):
        for path in iter_jsonl_paths(folder):
            for record in load_jsonl(path):
                key = promotion_key(record)

                if not key:
                    continue

                source_key = ""

                source_item_id = normalize_text(record.get("source_item_id"))
                if source_item_id and source_item_id in item_lookup:
                    source_key = item_lookup[source_item_id]

                if not source_key:
                    source_key = item_source_key(record)

                if source_key:
                    promotions_by_source[source_key].add(key)

    return promotions_by_source


def performance_score(promotion_hit_rate, entity_yield, theme_yield, duplicate_yield):
    return round(
        100
        * (
            0.35 * promotion_hit_rate
            + 0.25 * entity_yield
            + 0.20 * theme_yield
            + 0.20 * (1.0 - duplicate_yield)
        ),
        2,
    )


def score_source(entry, source_metrics):
    registry_signal = clamp(entry["trust_score"] - entry["noise_score"], 0, 100)
    observed_signal = performance_score(
        source_metrics["promotion_hit_rate"],
        source_metrics["entity_yield"],
        source_metrics["theme_yield"],
        source_metrics["duplicate_yield"],
    )

    if source_metrics["item_count"] == 0:
        source_score = float(registry_signal)
    else:
        source_score = round((0.5 * registry_signal) + (0.5 * observed_signal), 2)

    if source_score >= 80:
        quality_tier = "preferred"
    elif source_score >= 60:
        quality_tier = "usable"
    else:
        quality_tier = "noisy"

    return {
        "registry_signal": registry_signal,
        "observed_signal": observed_signal,
        "source_score": source_score,
        "quality_tier": quality_tier,
    }


def summarize_source(entry, items, promoted_hashes):
    items = sorted(
        items,
        key=lambda item: (
            normalize_text(item.get("timestamp") or item.get("created_at") or ""),
            normalize_text(item.get("item_id") or item.get("source_item_id") or ""),
            normalize_text(item.get("source_name") or ""),
        ),
    )

    seen_signatures = set()
    duplicate_count = 0
    entity_item_count = 0
    theme_item_count = 0

    for item in items:
        signature = narrative_signature(item)

        if signature:
            if signature in seen_signatures:
                duplicate_count += 1
            else:
                seen_signatures.add(signature)

        if item_entity_count(item) > 0:
            entity_item_count += 1

        if item_theme_count(item) > 0:
            theme_item_count += 1

    item_count = len(items)
    promoted_count = len(promoted_hashes)
    non_duplicate_count = max(1, item_count - duplicate_count)

    source_metrics = {
        **{key: value for key, value in entry.items() if key != "source_key"},
        "item_count": item_count,
        "promoted_count": promoted_count,
        "duplicate_count": duplicate_count,
        "entity_item_count": entity_item_count,
        "theme_item_count": theme_item_count,
        "promotion_frequency": round(promoted_count / item_count, 4) if item_count else 0.0,
        "promotion_hit_rate": round(promoted_count / non_duplicate_count, 4) if item_count else 0.0,
        "entity_yield": round(entity_item_count / item_count, 4) if item_count else 0.0,
        "theme_yield": round(theme_item_count / item_count, 4) if item_count else 0.0,
        "duplicate_yield": round(duplicate_count / item_count, 4) if item_count else 0.0,
    }
    source_metrics.update(score_source(entry, source_metrics))
    return source_metrics


def compute_source_metrics(
    intake_log_path=DEFAULT_INPUT_LOG_PATH,
    source_registry_path=DEFAULT_SOURCE_REGISTRY_PATH,
    event_dir=DEFAULT_EVENT_DIR,
    hermes_dir=DEFAULT_HERMES_DIR,
    output_path=DEFAULT_OUTPUT_PATH,
):
    intake_log_path = Path(intake_log_path)
    source_registry_path = Path(source_registry_path)
    event_dir = Path(event_dir)
    hermes_dir = Path(hermes_dir)
    output_path = Path(output_path)

    registry = load_source_registry(source_registry_path)
    items = load_items(intake_log_path)
    item_lookup = build_item_lookup(items)
    promotions_by_source = build_promotion_index(event_dir, hermes_dir, item_lookup)

    grouped_items = defaultdict(list)
    unregistered_items = defaultdict(list)

    registry_lookup = {entry["source_key"]: entry for entry in registry}

    for index, item in enumerate(items):
        source_key = item_source_key(item)

        if source_key in registry_lookup:
            grouped_items[source_key].append(item)
        else:
            unregistered_items[source_key].append(item)

    source_metrics = []

    for entry in registry:
        source_key = entry["source_key"]
        source_metrics.append(
            summarize_source(
                entry,
                grouped_items.get(source_key, []),
                promotions_by_source.get(source_key, set()),
            )
        )

    unregistered_metrics = []

    for source_key in sorted(unregistered_items):
        items_for_source = unregistered_items[source_key]
        promoted_hashes = promotions_by_source.get(source_key, set())
        display_entry = {
            "source_id": source_key or "unknown",
            "source_key": source_key or "unknown",
            "platform": "unregistered",
            "category": "unregistered",
            "verticals": [],
            "priority": "low",
            "trust_score": 0,
            "noise_score": 0,
            "enabled": False,
            "tags": [],
        }
        unregistered_metrics.append(
            summarize_source(display_entry, items_for_source, promoted_hashes)
        )

    result = {
        "source_count": len(registry),
        "item_count": len(items),
        "registered_item_count": sum(entry["item_count"] for entry in source_metrics),
        "unregistered_item_count": sum(entry["item_count"] for entry in unregistered_metrics),
        "promoted_item_count": sum(entry["promoted_count"] for entry in source_metrics)
        + sum(entry["promoted_count"] for entry in unregistered_metrics),
        "sources": source_metrics,
        "unregistered_sources": unregistered_metrics,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return {
        "output_path": output_path,
        "source_count": len(registry),
        "item_count": len(items),
        "source_metrics": source_metrics,
        "unregistered_sources": unregistered_metrics,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Build deterministic source metrics from the canonical AEON source registry."
    )
    parser.add_argument(
        "--intake-log",
        default=str(DEFAULT_INPUT_LOG_PATH),
        help="Canonical processed intake log used to measure source quality.",
    )
    parser.add_argument(
        "--source-registry",
        default=str(DEFAULT_SOURCE_REGISTRY_PATH),
        help="Canonical source registry YAML file.",
    )
    parser.add_argument(
        "--events-dir",
        default=str(DEFAULT_EVENT_DIR),
        help="Append-only Hermes promotion event directory.",
    )
    parser.add_argument(
        "--hermes-dir",
        default=str(DEFAULT_HERMES_DIR),
        help="Materialized Hermes promotion directory.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Path for the source metrics JSON output.",
    )
    args = parser.parse_args()

    result = compute_source_metrics(
        intake_log_path=Path(args.intake_log),
        source_registry_path=Path(args.source_registry),
        event_dir=Path(args.events_dir),
        hermes_dir=Path(args.hermes_dir),
        output_path=Path(args.output),
    )

    print(
        "Wrote source metrics for {} sources to {}.".format(
            result["source_count"],
            result["output_path"],
        )
    )


if __name__ == "__main__":
    main()
