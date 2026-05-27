import json
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ingestion.build_entity_summary import (  # noqa: E402
    clean_text,
    entity_key,
    extract_entities,
    extract_item_text,
    item_id,
    item_source_name,
    item_timestamp,
    load_configured_entities,
    load_items,
    normalize_entity_type,
)


DEFAULT_LOG_PATH = Path("data/processed/intake_log.jsonl")
DEFAULT_ENTITY_SUMMARY_PATH = Path("data/processed/entity_summary.json")
DEFAULT_OUTPUT_PATH = Path("data/processed/narrative_summary.json")
DEFAULT_ALERTS_PATH = Path("data/processed/alert_candidates.jsonl")
DEFAULT_HERMES_DIR = Path("data/hermes/promoted")
DEFAULT_ENTITIES_PATH = Path("config/entities.yml")
DEFAULT_WATCHLIST_PATH = Path("config/watchlist.yml")
DEFAULT_SOURCES_PATH = Path("config/sources.yml")
DEFAULT_NARRATIVE_LIMIT = 5


CLUSTER_DEFINITIONS = [
    {
        "label": "Venice/Dolphin thesis",
        "priority": 500,
        "entity_keys": {"venice", "dolphin"},
        "patterns": [],
    },
    {
        "label": "Base/Coinbase ecosystem",
        "priority": 400,
        "entity_keys": {"base"},
        "patterns": [
            r"\bcoinbase base\b",
            r"\bbase ecosystem\b",
            r"\bbase chain\b",
            r"\bbase app\b",
            r"\bbase mainnet\b",
            r"\bbase network\b",
        ],
    },
    {
        "label": "AI inference market",
        "priority": 300,
        "entity_keys": {"openrouter"},
        "patterns": [
            r"\binference routing\b",
            r"\bmodel routing\b",
            r"\binference market\b",
            r"\binference stack\b",
        ],
    },
    {
        "label": "RWA/tokenization",
        "priority": 200,
        "entity_keys": {"rwa"},
        "patterns": [
            r"\btokenization\b",
            r"\btokenized assets\b",
            r"\btokenised assets\b",
            r"\breal world assets?\b",
            r"\bprivate credit\b",
        ],
    },
    {
        "label": "stablecoin regulation",
        "priority": 250,
        "entity_keys": set(),
        "patterns": [
            r"\bstablecoin(?:s)?\b",
            r"\bregulation\b",
            r"\bregulatory\b",
            r"\bcompliance\b",
            r"\bpolicy\b",
            r"\bbill\b",
            r"\btreasury\b",
            r"\blegislation\b",
            r"\bissuer\b",
        ],
        "required_groups": [
            [r"\bstablecoin(?:s)?\b"],
            [
                r"\bregulation\b",
                r"\bregulatory\b",
                r"\bcompliance\b",
                r"\bpolicy\b",
                r"\bbill\b",
                r"\btreasury\b",
                r"\blegislation\b",
                r"\bissuer\b",
            ],
        ],
    },
]


def load_json(path):
    path = Path(path)

    if not path.exists():
        return None

    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl_records(path):
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


def load_jsonl_dir(path):
    path = Path(path)

    if not path.exists():
        return []

    records = []

    for jsonl_path in sorted(path.glob("*.jsonl")):
        records.extend(load_jsonl_records(jsonl_path))

    return records


def normalize_timestamp_value(value):
    parsed = item_timestamp({"timestamp": value})

    if parsed is None:
        return ""

    return parsed.isoformat()


def infer_sibling_path(reference_path, filename):
    reference_path = Path(reference_path)
    return reference_path.parent / filename


def canonical_text_for_record(record):
    return extract_item_text(record)


def match_pattern(pattern, text):
    return re.search(pattern, text, re.IGNORECASE) is not None


def group_has_match(group, entity_keys, text):
    for pattern in group:
        if match_pattern(pattern, text):
            return True

        lowered = re.sub(r"[^a-z0-9]+", " ", pattern.lower()).strip()

        if lowered and lowered in entity_keys:
            return True

    return False


def cluster_score(definition, entity_keys, text):
    if definition.get("required_groups"):
        for group in definition["required_groups"]:
            if not group_has_match(group, entity_keys, text):
                return 0

        pattern_hits = sum(
            1
            for pattern in definition.get("patterns", [])
            if match_pattern(pattern, text)
        )
        entity_hits = len(entity_keys & definition.get("entity_keys", set()))
        return definition["priority"] + pattern_hits + entity_hits

    pattern_hits = sum(
        1
        for pattern in definition.get("patterns", [])
        if match_pattern(pattern, text)
    )
    entity_hits = len(entity_keys & definition.get("entity_keys", set()))

    if not pattern_hits and not entity_hits:
        return 0

    return definition["priority"] + (entity_hits * 3) + pattern_hits


def best_cluster_for_item(item, entity_keys):
    text = canonical_text_for_record(item)
    best_definition = None
    best_score = 0

    for definition in CLUSTER_DEFINITIONS:
        score = cluster_score(definition, entity_keys, text)

        if score <= 0:
            continue

        if best_definition is None or score > best_score:
            best_definition = definition
            best_score = score
            continue

        if score == best_score and definition["priority"] > best_definition["priority"]:
            best_definition = definition
            best_score = score

    return best_definition, best_score


def load_alert_items(alerts_path):
    return load_jsonl_records(alerts_path)


def load_promotion_items(hermes_dir):
    return load_jsonl_dir(hermes_dir)


def build_membership_maps(items, configured_entities):
    item_to_entity_keys = {}
    entity_to_items = defaultdict(list)

    for item in items:
        item_text = canonical_text_for_record(item)
        extracted_entities = extract_entities(
            item_text,
            configured_entities=configured_entities,
        )
        entity_keys = []

        for entity in extracted_entities:
            key = entity.get("entity_key")

            if key and key not in entity_keys:
                entity_keys.append(key)

        normalized_item_id = clean_text(item.get("item_id") or item.get("id") or item.get("source_item_id"))
        item_to_entity_keys[normalized_item_id] = entity_keys

        for entity_key_value in entity_keys:
            entity_to_items[entity_key_value].append(item)

    return item_to_entity_keys, entity_to_items


def build_entity_records(
    entity_summary,
    alert_items,
    promotion_items,
    prior_entities_by_key,
    configured_entities,
):
    entities = entity_summary.get("entities") or []
    alert_membership = defaultdict(set)
    promotion_membership = defaultdict(set)
    alias_membership = defaultdict(set)

    for item in alert_items:
        item_text = canonical_text_for_record(item)
        item_identifier = clean_text(item.get("item_id") or item.get("id") or item.get("source_item_id"))
        extracted_entities = extract_entities(item_text, configured_entities=configured_entities)

        for entity in extracted_entities:
            entity_key_value = entity.get("entity_key")

            if entity_key_value:
                alert_membership[entity_key_value].add(item_identifier)

    for item in promotion_items:
        item_text = canonical_text_for_record(item)
        item_identifier = clean_text(
            item.get("promotion_hash")
            or item.get("event_id")
            or item.get("source_item_id")
            or item.get("item_id")
            or item.get("id")
        )
        extracted_entities = extract_entities(item_text, configured_entities=configured_entities)

        for entity in extracted_entities:
            entity_key_value = entity.get("entity_key")

            if entity_key_value:
                promotion_membership[entity_key_value].add(item_identifier)

    entity_records = []

    for entity in entities:
        entity_key_value = clean_text(entity.get("entity_key"))
        mentions = entity.get("mentions") or []
        mention_timestamps = [
            item_timestamp(mention)
            for mention in mentions
            if item_timestamp(mention) is not None
        ]
        first_seen = min(mention_timestamps).isoformat() if mention_timestamps else ""
        last_seen = max(mention_timestamps).isoformat() if mention_timestamps else ""
        aliases_seen = sorted(
            {
                clean_text(
                    mention.get("matched_alias")
                    or mention.get("entity_name")
                    or entity.get("entity_name")
                )
                for mention in mentions
                if clean_text(
                    mention.get("matched_alias")
                    or mention.get("entity_name")
                    or entity.get("entity_name")
                )
            }
        )
        prior_entity = prior_entities_by_key.get(entity_key_value, {})
        trend_status = classify_trend_status(
            mention_count=entity.get("mention_count", 0),
            source_count=entity.get("source_diversity", 0),
            prior_mention_count=prior_entity.get("mention_count", 0),
            prior_source_count=prior_entity.get("source_count", 0),
        )
        current_verticals = list(entity.get("associated_verticals") or [])
        current_verticals = [vertical for vertical in current_verticals if clean_text(vertical)]
        record = {
            "entity_key": entity_key_value,
            "canonical_name": clean_text(entity.get("entity_name")),
            "aliases_seen": aliases_seen,
            "verticals": current_verticals,
            "entity_type": normalize_entity_type(entity.get("entity_type")),
            "mention_count": int(entity.get("mention_count", 0)),
            "source_count": int(entity.get("source_diversity", 0)),
            "alert_count": len(alert_membership.get(entity_key_value, set())),
            "promotion_count": len(promotion_membership.get(entity_key_value, set())),
            "first_seen": prior_entity.get("first_seen") or first_seen,
            "last_seen": max_iso_timestamp(
                prior_entity.get("last_seen"),
                last_seen,
            ),
            "trend_status": trend_status,
            "entity_confidence": round(float(entity.get("entity_confidence", 0.0)), 2),
        }
        record["priority_score"] = narrative_priority_score(record)
        entity_records.append(record)

        if aliases_seen:
            alias_membership[entity_key_value].update(aliases_seen)

    entity_records = sorted(
        entity_records,
        key=lambda record: (
            -record["priority_score"],
            -record["mention_count"],
            -record["source_count"],
            record["canonical_name"].lower(),
        ),
    )

    return entity_records


def classify_trend_status(
    mention_count,
    source_count,
    prior_mention_count,
    prior_source_count,
):
    mention_count = int(mention_count or 0)
    source_count = int(source_count or 0)
    prior_mention_count = int(prior_mention_count or 0)
    prior_source_count = int(prior_source_count or 0)

    if prior_mention_count <= 0 and prior_source_count <= 0:
        return "new"

    mention_rising = (
        prior_mention_count > 0
        and mention_count >= max(prior_mention_count + 1, int(prior_mention_count * 1.35))
    )
    source_rising = (
        prior_source_count > 0
        and source_count >= max(prior_source_count + 1, int(prior_source_count * 1.25))
    )

    if mention_rising or source_rising:
        return "rising"

    mention_fading = prior_mention_count > 0 and mention_count <= int(prior_mention_count * 0.75)
    source_fading = prior_source_count > 0 and source_count <= int(prior_source_count * 0.8)

    if mention_fading and source_fading:
        return "fading"

    return "stable"


def narrative_priority_score(record):
    score = (
        record.get("mention_count", 0)
        + (record.get("source_count", 0) * 2)
        + (record.get("alert_count", 0) * 1.5)
        + (record.get("promotion_count", 0) * 2.5)
    )

    trend = record.get("trend_status")

    if trend == "new":
        score += 2
    elif trend == "rising":
        score += 1.5
    elif trend == "fading":
        score -= 1

    return round(score, 2)


def max_iso_timestamp(*values):
    parsed_values = []

    for value in values:
        if not value:
            continue

        parsed = item_timestamp({"timestamp": value})

        if parsed is not None:
            parsed_values.append(parsed)

    if not parsed_values:
        return ""

    return max(parsed_values).isoformat()


def build_narratives(
    items,
    alert_items,
    promotion_items,
    configured_entities,
    prior_narratives_by_label,
):
    narrative_members = defaultdict(list)
    narrative_seen_items = defaultdict(set)
    narrative_aliases = defaultdict(set)
    narrative_verticals = defaultdict(set)
    narrative_first_seen = {}
    narrative_last_seen = {}
    narrative_entity_types = defaultdict(Counter)

    alert_membership = defaultdict(set)
    promotion_membership = defaultdict(set)

    for item in alert_items:
        item_text = canonical_text_for_record(item)
        item_identifier = clean_text(item.get("item_id") or item.get("id") or item.get("source_item_id"))
        extracted_entities = extract_entities(item_text, configured_entities=configured_entities)
        entity_keys = {entity.get("entity_key") for entity in extracted_entities if entity.get("entity_key")}

        for definition in CLUSTER_DEFINITIONS:
            score = cluster_score(definition, entity_keys, item_text)

            if score > 0:
                alert_membership[definition["label"]].add(item_identifier)

    for item in promotion_items:
        item_text = canonical_text_for_record(item)
        item_identifier = clean_text(
            item.get("promotion_hash")
            or item.get("event_id")
            or item.get("source_item_id")
            or item.get("item_id")
            or item.get("id")
        )
        extracted_entities = extract_entities(item_text, configured_entities=configured_entities)
        entity_keys = {entity.get("entity_key") for entity in extracted_entities if entity.get("entity_key")}

        for definition in CLUSTER_DEFINITIONS:
            score = cluster_score(definition, entity_keys, item_text)

            if score > 0:
                promotion_membership[definition["label"]].add(item_identifier)

    for item in items:
        item_text = canonical_text_for_record(item)
        extracted_entities = extract_entities(item_text, configured_entities=configured_entities)
        entity_keys = {entity.get("entity_key") for entity in extracted_entities if entity.get("entity_key")}
        cluster_definition, _cluster_score = best_cluster_for_item(item, entity_keys)

        if cluster_definition is None:
            continue

        cluster_label = cluster_definition["label"]
        item_identifier = clean_text(item.get("item_id") or item.get("id") or item.get("source_item_id"))

        if item_identifier in narrative_seen_items[cluster_label]:
            continue

        narrative_seen_items[cluster_label].add(item_identifier)
        narrative_members[cluster_label].append(item)

        item_timestamp_value = item_timestamp(item)

        if item_timestamp_value is not None:
            item_timestamp_text = item_timestamp_value.isoformat()
            current_first = narrative_first_seen.get(cluster_label, "")
            current_last = narrative_last_seen.get(cluster_label, "")

            if not current_first or item_timestamp_text < current_first:
                narrative_first_seen[cluster_label] = item_timestamp_text

            if not current_last or item_timestamp_text > current_last:
                narrative_last_seen[cluster_label] = item_timestamp_text

        verticals = item.get("verticals") or []

        for vertical in verticals:
            vertical_text = clean_text(vertical)

            if vertical_text:
                narrative_verticals[cluster_label].add(vertical_text)

        for entity in extracted_entities:
            entity_key_value = entity.get("entity_key")
            entity_type = entity.get("entity_type", "unknown")
            entity_name = entity.get("entity_name")

            if entity_key_value:
                if entity_name:
                    narrative_aliases[cluster_label].add(clean_text(entity_name))
                narrative_entity_types[cluster_label][normalize_entity_type(entity_type)] += 1

    narratives = []

    for definition in CLUSTER_DEFINITIONS:
        label = definition["label"]
        items_for_cluster = narrative_members.get(label, [])

        if not items_for_cluster:
            continue

        source_names = sorted(
            {
                item_source_name(item)
                for item in items_for_cluster
                if item_source_name(item)
            }
        )
        mention_count = len(items_for_cluster)
        source_count = len(source_names)
        first_seen = narrative_first_seen.get(label, "")
        last_seen = narrative_last_seen.get(label, "")
        prior_narrative = prior_narratives_by_label.get(label, {})
        trend_status = classify_trend_status(
            mention_count=mention_count,
            source_count=source_count,
            prior_mention_count=prior_narrative.get("mention_count", 0),
            prior_source_count=prior_narrative.get("source_count", 0),
        )
        verticals = sorted(
            narrative_verticals.get(label, set()),
            key=str.lower,
        )
        alert_count = len(alert_membership.get(label, set()))
        promotion_count = len(promotion_membership.get(label, set()))
        canonical_entities = sorted(
            {
                entity.get("entity_name")
                for item in items_for_cluster
                for entity in extract_entities(
                    canonical_text_for_record(item),
                    configured_entities=configured_entities,
                )
                if entity.get("entity_name")
            },
            key=str.lower,
        )
        entity_type = "mixed"

        if narrative_entity_types.get(label):
            dominant_type = narrative_entity_types[label].most_common(1)[0][0]
            entity_type = dominant_type

        record = {
            "narrative_name": label,
            "canonical_entities": canonical_entities,
            "aliases_seen": sorted(narrative_aliases.get(label, set()), key=str.lower),
            "verticals": verticals,
            "entity_type": entity_type,
            "mention_count": mention_count,
            "source_count": source_count,
            "alert_count": alert_count,
            "promotion_count": promotion_count,
            "first_seen": prior_narrative.get("first_seen") or first_seen,
            "last_seen": max_iso_timestamp(prior_narrative.get("last_seen"), last_seen),
            "trend_status": trend_status,
        }
        record["priority_score"] = narrative_priority_score(record)
        narratives.append(record)

    narratives = sorted(
        narratives,
        key=lambda record: (
            -record["priority_score"],
            -record["mention_count"],
            -record["source_count"],
            record["narrative_name"].lower(),
        ),
    )

    return narratives


def build_narrative_summary(
    log_path=DEFAULT_LOG_PATH,
    entity_summary_path=None,
    entity_dir=None,
    output_path=DEFAULT_OUTPUT_PATH,
    alerts_path=DEFAULT_ALERTS_PATH,
    hermes_dir=DEFAULT_HERMES_DIR,
    entities_path=DEFAULT_ENTITIES_PATH,
    watchlist_path=DEFAULT_WATCHLIST_PATH,
    sources_path=DEFAULT_SOURCES_PATH,
):
    log_path = Path(log_path)
    output_path = Path(output_path)
    alerts_path = Path(alerts_path)
    hermes_dir = Path(hermes_dir)

    if entity_summary_path is None:
        entity_summary_path = infer_sibling_path(log_path, "entity_summary.json")

    entity_summary_path = Path(entity_summary_path)
    if entity_dir is None:
        entity_dir = entity_summary_path.parent / "entities"

    entity_dir = Path(entity_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not entity_summary_path.exists():
        from scripts.ingestion.build_entity_summary import (
            build_entity_summary as build_entity_summary_artifact,
        )

        build_entity_summary_artifact(
            log_path=log_path,
            output_path=entity_summary_path,
            entity_dir=entity_dir,
            entities_path=entities_path,
            watchlist_path=watchlist_path,
            sources_path=sources_path,
        )

    entity_summary = load_json(entity_summary_path) or {
        "entities": [],
        "entity_count": 0,
    }
    prior_summary = load_json(output_path) or {}
    prior_entities_by_key = {
        clean_text(entity.get("entity_key")): entity
        for entity in prior_summary.get("entities", [])
        if clean_text(entity.get("entity_key"))
    }
    prior_narratives_by_label = {
        clean_text(narrative.get("narrative_name")): narrative
        for narrative in prior_summary.get("narratives", [])
        if clean_text(narrative.get("narrative_name"))
    }

    items = load_items(log_path)
    alert_items = load_alert_items(alerts_path)
    promotion_items = load_promotion_items(hermes_dir)
    configured_entities = load_configured_entities(
        entities_path,
        watchlist_path,
        sources_path,
    )

    entities = build_entity_records(
        entity_summary=entity_summary,
        alert_items=alert_items,
        promotion_items=promotion_items,
        prior_entities_by_key=prior_entities_by_key,
        configured_entities=configured_entities,
    )
    narratives = build_narratives(
        items=items,
        alert_items=alert_items,
        promotion_items=promotion_items,
        configured_entities=configured_entities,
        prior_narratives_by_label=prior_narratives_by_label,
    )
    top_narratives = narratives[:DEFAULT_NARRATIVE_LIMIT]

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "log_path": str(log_path),
        "entity_summary_path": str(entity_summary_path),
        "alerts_path": str(alerts_path),
        "hermes_dir": str(hermes_dir),
        "prior_generated_at": prior_summary.get("generated_at", ""),
        "entity_count": len(entities),
        "narrative_count": len(narratives),
        "entities": entities,
        "narratives": narratives,
        "top_narratives": top_narratives,
    }

    output_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return summary


def main():
    summary = build_narrative_summary()
    print(f"Generated {summary['narrative_count']} narratives.")


if __name__ == "__main__":
    main()
