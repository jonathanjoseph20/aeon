import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ingestion.build_entity_summary import (  # noqa: E402
    classify_trend,
    extract_entities,
    load_configured_entities,
    parse_timestamp,
)


DEFAULT_INPUT_LOG = Path("data/processed/intake_log.jsonl")
DEFAULT_EVENT_DIR = Path("data/events/promote_to_hermes")
DEFAULT_HERMES_DIR = Path("data/hermes/promoted")
DEFAULT_IMPORTANCE_THRESHOLD = 7
DEFAULT_PROMOTION_SCORE_THRESHOLD = 15.0
DEFAULT_PROMOTION_CONFIDENCE_THRESHOLD = 96
DEFAULT_MIN_SIGNAL_COUNT = 3
DEFAULT_MIN_SIGNAL_COUNT_WITH_OVERRIDE = 2
DEFAULT_WEIGHTS = {
    "alert_severity": 6.0,
    "source_priority": {
        "high": 6.0,
        "medium": 0.0,
        "low": 0.0,
    },
    "watchlist": 0.5,
    "entity_trend": 1.5,
    "source_diversity": 5.0,
}
HIGH_IMPORTANCE_SIGNAL_THRESHOLD = 9
LOW_INFORMATION_TWEET_WORD_LIMIT = 18
STRONG_ENTITY_SOURCE_DIVERSITY_THRESHOLD = 4
STRONG_ENTITY_SOURCE_TYPE_DIVERSITY_THRESHOLD = 2
GENERIC_HERMES_SUPPRESSION_PATTERNS = (
    r"\bstablecoin(?:s)?\b",
    r"\brwa\b",
    r"\btokeni[sz]ation\b",
    r"\btokenized\b",
    r"\breal world assets?\b",
    r"\bprivate credit\b",
)
GENERIC_MARKET_COMMENTARY_PATTERNS = (
    r"\bmarket wrap\b",
    r"\bmarket commentary\b",
    r"\bweekly market\b",
    r"\bwatching the tape\b",
    r"\bwatching markets\b",
    r"\bmarket feels\b",
    r"\brisk on\b",
    r"\brisk off\b",
    r"\bstocks? (are |is )?(higher|lower|mixed)\b",
    r"\bbonds? (are |is )?(higher|lower|mixed)\b",
    r"\bjust another day\b",
)
GENERIC_MARKET_COMMENTARY_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in GENERIC_MARKET_COMMENTARY_PATTERNS),
    re.IGNORECASE,
)
GENERIC_HERMES_SUPPRESSION_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in GENERIC_HERMES_SUPPRESSION_PATTERNS),
    re.IGNORECASE,
)


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


def load_jsonl(path):
    if not path.exists():
        return []

    records = []

    for line in path.read_text().splitlines():
        if not line.strip():
            continue

        record = json.loads(line)

        if isinstance(record, dict):
            records.append(record)

    return records


def normalize_list(value):
    if not value:
        return []

    if isinstance(value, str):
        values = [value]
    else:
        values = list(value)

    normalized = []
    seen = set()

    for entry in values:
        text = str(entry or "").strip()

        if not text or text in seen:
            continue

        seen.add(text)
        normalized.append(text)

    return normalized


def first_non_empty(*values):
    for value in values:
        if value in (None, ""):
            continue

        return value

    return ""


def safe_text(value):
    return str(value or "").strip()


def normalize_whitespace(value):
    return re.sub(r"\s+", " ", safe_text(value)).strip()


def build_signal_band(item):
    explicit = safe_text(item.get("signal_band"))

    if explicit:
        return explicit

    score = safe_int(item.get("importance_score"), 0)

    if score >= 8:
        return "High Signal"

    if score >= 4:
        return "Normal Digest"

    return "Low Priority"


def get_dedupe_hash(item):
    dedupe_hash = safe_text(item.get("dedupe_hash"))

    if dedupe_hash:
        return dedupe_hash

    item_id = safe_text(item.get("item_id"))

    if item_id:
        return item_id

    fallback = {
        "source_type": safe_text(item.get("source_type")).lower(),
        "source_name": safe_text(item.get("source_name")).lower(),
        "subject": safe_text(item.get("subject")).lower(),
        "summary": safe_text(item.get("summary")).lower(),
        "preview": safe_text(item.get("content_preview") or item.get("preview")).lower(),
        "timestamp": safe_text(item.get("timestamp") or item.get("created_at")),
        "source_url": safe_text(item.get("source_url")),
    }

    return hashlib.sha256(
        json.dumps(fallback, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


def get_promotion_hash(item):
    dedupe_hash = get_dedupe_hash(item)
    payload = f"promote_to_hermes::{dedupe_hash}"

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def get_importance_score(item):
    return safe_int(item.get("importance_score"), 0)


def get_effective_threshold(item, threshold):
    override = item.get("promotion_threshold_override")

    if override in (None, ""):
        return threshold

    return safe_float(override, threshold)


def build_summary_and_preview(item):
    preview = safe_text(
        first_non_empty(
            item.get("content_preview"),
            item.get("preview"),
            item.get("content"),
            item.get("raw_text"),
            item.get("summary"),
        )
    )
    summary = safe_text(first_non_empty(item.get("summary"), preview))

    return summary, preview


def unique_tags(item):
    tags = normalize_list(item.get("tags"))
    verticals = normalize_list(item.get("verticals"))

    if not tags:
        return verticals

    return tags


def build_notification_payload(source_name, signal_band, importance_score, confidence, summary):
    text = "AEON promoted {} ({}, score {}, confidence {}): {}".format(
        source_name or "Unknown source",
        signal_band,
        importance_score,
        confidence,
        summary or "No summary available",
    )

    return {
        "text": text[:2800],
        "confidence": confidence,
    }


def build_narrative_signature(item):
    parts = [
        item.get("subject"),
        item.get("summary"),
        item.get("content_preview") or item.get("preview"),
        item.get("content"),
        item.get("raw_text"),
    ]
    cleaned = [normalize_whitespace(part).lower() for part in parts if normalize_whitespace(part)]

    if not cleaned:
        fallback_parts = [
            safe_text(item.get("source_name")).lower(),
            safe_text(item.get("source_url")).lower(),
        ]
        cleaned = [part for part in fallback_parts if part]

    return hashlib.sha256(" || ".join(cleaned).encode("utf-8")).hexdigest()[:16]


def build_item_text(item):
    return normalize_whitespace(
        " ".join(
            part
            for part in (
                item.get("subject"),
                item.get("summary"),
                item.get("content_preview") or item.get("preview"),
                item.get("content"),
                item.get("raw_text"),
                item.get("source_name"),
            )
            if safe_text(part)
        )
    )


def is_low_information_tweet(item, item_text):
    if safe_text(item.get("source_type")).lower() != "twitter":
        return False

    if item.get("promotion_threshold_override") not in (None, ""):
        return False

    if get_importance_score(item) >= HIGH_IMPORTANCE_SIGNAL_THRESHOLD:
        return False

    word_count = len(re.findall(r"\b\w+\b", item_text))
    return word_count < LOW_INFORMATION_TWEET_WORD_LIMIT


def is_generic_market_commentary(item, item_text):
    if item.get("promotion_threshold_override") not in (None, ""):
        return False

    return bool(GENERIC_MARKET_COMMENTARY_RE.search(item_text))


def is_generic_hermes_term(item, item_text):
    if item.get("promotion_threshold_override") not in (None, ""):
        return False

    return bool(GENERIC_HERMES_SUPPRESSION_RE.search(item_text))


def build_entity_context(items):
    configured_entities = load_configured_entities()
    entity_aggregates = {}
    item_entity_keys = []

    for index, item in enumerate(items):
        item_text = build_item_text(item)
        extracted = extract_entities(item_text, configured_entities=configured_entities)
        unique_entities = []
        seen_keys = set()

        for entity in extracted:
            entity_key = entity["entity_key"]

            if entity_key in seen_keys:
                continue

            seen_keys.add(entity_key)
            unique_entities.append(entity)

        item_entity_keys.append([entity["entity_key"] for entity in unique_entities])

        item_timestamp = parse_timestamp(item.get("timestamp") or item.get("created_at"))
        item_importance = get_importance_score(item)
        source_name = safe_text(item.get("source_name") or "Unknown")
        source_type = safe_text(item.get("source_type"))

        for entity in unique_entities:
            key = entity["entity_key"]
            aggregate = entity_aggregates.setdefault(
                key,
                {
                    "entity_key": key,
                    "entity_name": entity["entity_name"],
                    "mention_count": 0,
                    "source_names": set(),
                    "source_types": set(),
                    "importance_total": 0,
                    "mentions": [],
                },
            )

            aggregate["mention_count"] += 1
            aggregate["source_names"].add(source_name)
            aggregate["source_types"].add(source_type)
            aggregate["importance_total"] += item_importance
            aggregate["mentions"].append(
                {
                    "timestamp": item_timestamp.isoformat() if item_timestamp else "",
                    "importance_score": item_importance,
                    "index": index,
                }
            )

    resolved_aggregates = {}

    for key, aggregate in entity_aggregates.items():
        trend_label, trend_score = classify_trend(aggregate["mentions"])
        source_names = sorted(aggregate["source_names"])
        source_types = sorted(aggregate["source_types"])
        mention_count = aggregate["mention_count"]

        resolved_aggregates[key] = {
            "entity_key": key,
            "entity_name": aggregate["entity_name"],
            "mention_count": mention_count,
            "source_names": source_names,
            "source_types": source_types,
            "source_diversity": len(source_names),
            "source_type_diversity": len(source_types),
            "average_importance_score": round(
                aggregate["importance_total"] / mention_count, 2
            ) if mention_count else 0.0,
            "trend_label": trend_label,
            "trend_score": trend_score,
        }

    item_entity_contexts = []

    for entity_keys in item_entity_keys:
        item_entity_contexts.append(
            [
                resolved_aggregates[key]
                for key in entity_keys
                if key in resolved_aggregates
            ]
        )

    return item_entity_contexts


def build_promotion_evidence(item, entity_contexts, weights, importance_threshold):
    item_text = build_item_text(item)
    signal_threshold = safe_float(
        item.get("promotion_threshold_override"),
        importance_threshold,
    )
    importance_score = get_importance_score(item)
    signal_band = build_signal_band(item)
    source_priority = safe_text(item.get("priority") or "low").lower()
    supporting_signals = []
    score = 0.0
    confidence = 0.0
    reasons = []
    signal_details = []
    entity_evidence = []
    best_entity = None
    best_trend_entity = None
    best_trend_score = 0.0
    watchlist_hits = item.get("watchlist_hits") or []

    def add_supporting_signal(signal_name, reason, score_component, confidence_component, detail):
        nonlocal score, confidence

        if signal_name not in supporting_signals:
            supporting_signals.append(signal_name)

        if reason:
            reasons.append(reason)

        score += score_component
        confidence += confidence_component
        signal_details.append(detail)

    for entity in entity_contexts:
        if best_entity is None:
            best_entity = entity
        elif (
            entity["source_diversity"] > best_entity["source_diversity"]
            or (
                entity["source_diversity"] == best_entity["source_diversity"]
                and entity["source_type_diversity"] > best_entity["source_type_diversity"]
            )
            or (
                entity["source_diversity"] == best_entity["source_diversity"]
                and entity["source_type_diversity"] == best_entity["source_type_diversity"]
                and entity["mention_count"] > best_entity["mention_count"]
            )
        ):
            best_entity = entity

        if entity["trend_score"] > best_trend_score:
            best_trend_score = entity["trend_score"]
            best_trend_entity = entity

    has_high_priority_source = source_priority == "high"
    has_override = item.get("promotion_threshold_override") not in (None, "")
    has_portfolio_vertical = "Portfolio" in normalize_list(item.get("verticals"))
    has_high_signal = signal_band == "High Signal" and importance_score >= HIGH_IMPORTANCE_SIGNAL_THRESHOLD
    has_source_context = (
        has_override
        or has_portfolio_vertical
        or (best_entity is not None and best_entity["source_diversity"] >= 2)
    )

    if has_high_signal and has_high_priority_source and has_source_context:
        severity_component = round(weights["alert_severity"], 2)
        add_supporting_signal(
            "high_importance",
            f"importance_score>={signal_threshold:g}",
            severity_component,
            20,
            {
                "signal": "high_importance",
                "value": importance_score,
                "threshold": signal_threshold,
                "weight": weights["alert_severity"],
                "score_component": severity_component,
            },
        )

    if has_high_signal and has_high_priority_source and has_source_context:
        add_supporting_signal(
            "high_signal_band",
            "signal_band=High Signal",
            3.0,
            15,
            {
                "signal": "high_signal_band",
                "value": signal_band,
                "threshold": "High Signal",
                "weight": 3.0,
                "score_component": 3.0,
            },
        )

    priority_weight = weights["source_priority"].get(source_priority, 0.0)
    if has_high_priority_source and priority_weight > 0 and has_source_context:
        add_supporting_signal(
            "high_priority_source",
            f"source_priority={source_priority}",
            priority_weight,
            20,
            {
                "signal": "source_priority",
                "value": source_priority,
                "threshold": "high",
                "weight": priority_weight,
                "score_component": priority_weight,
            },
        )

    if has_override and has_source_context:
        override_component = 5.0
        add_supporting_signal(
            "explicit_high_priority_override",
            f"explicit_override={item.get('promotion_threshold_override')}",
            override_component,
            25,
            {
                "signal": "explicit_high_priority_override",
                "value": safe_float(item.get("promotion_threshold_override"), signal_threshold),
                "threshold": "present",
                "weight": override_component,
                "score_component": override_component,
            },
        )

    if has_portfolio_vertical and has_high_priority_source and has_source_context:
        portfolio_component = 2.5
        add_supporting_signal(
            "portfolio_critical",
            "verticals include Portfolio",
            portfolio_component,
            12,
            {
                "signal": "portfolio_critical",
                "value": "Portfolio",
                "threshold": "Portfolio",
                "weight": portfolio_component,
                "score_component": portfolio_component,
            },
        )

    if best_entity and best_entity["source_diversity"] >= STRONG_ENTITY_SOURCE_DIVERSITY_THRESHOLD:
        add_supporting_signal(
            "cross_source_entity_reinforcement",
            f"cross_source_entity={best_entity['entity_name']}:{best_entity['source_diversity']} sources",
            weights["source_diversity"],
            25,
            {
                "signal": "cross_source_entity_reinforcement",
                "value": {
                    "entity": best_entity["entity_name"],
                    "source_diversity": best_entity["source_diversity"],
                    "source_type_diversity": best_entity["source_type_diversity"],
                },
                "threshold": STRONG_ENTITY_SOURCE_DIVERSITY_THRESHOLD,
                "weight": weights["source_diversity"],
                "score_component": weights["source_diversity"],
            },
        )
        entity_evidence.append(best_entity)

    if (
        best_entity
        and best_entity["source_diversity"] >= STRONG_ENTITY_SOURCE_DIVERSITY_THRESHOLD
        and best_entity["source_type_diversity"] >= STRONG_ENTITY_SOURCE_TYPE_DIVERSITY_THRESHOLD
    ):
        source_type_component = round(weights["source_diversity"] * 0.75, 2)
        add_supporting_signal(
            "source_diversity",
            f"source_diversity={best_entity['source_type_diversity']} source types",
            source_type_component,
            15,
            {
                "signal": "source_diversity",
                "value": best_entity["source_type_diversity"],
                "threshold": STRONG_ENTITY_SOURCE_TYPE_DIVERSITY_THRESHOLD,
                "weight": source_type_component,
                "score_component": source_type_component,
            },
        )

    if (
        best_trend_entity
        and best_trend_score > 0
        and ("cross_source_entity_reinforcement" in supporting_signals or "source_diversity" in supporting_signals)
    ):
        trend_component = round(weights["entity_trend"] * max(best_trend_score, 0.0), 2)
        add_supporting_signal(
            "entity_trend",
            f"entity_trend={best_trend_entity['entity_name']}:{best_trend_score:+.3f}",
            trend_component,
            10,
            {
                "signal": "entity_trend",
                "value": {
                    "entity": best_trend_entity["entity_name"],
                    "trend_label": best_trend_entity["trend_label"],
                    "trend_score": best_trend_score,
                },
                "threshold": ">0",
                "weight": weights["entity_trend"],
                "score_component": trend_component,
            },
        )

    if watchlist_hits and len(supporting_signals) >= 2:
        watchlist_component = weights["watchlist"]

        for hit in watchlist_hits:
            watchlist_component += safe_float(hit.get("score_boost"), 0.0) * 0.1

        score += watchlist_component
        confidence += 3
        hit_names = ", ".join(
            normalize_whitespace(hit.get("entity"))
            for hit in watchlist_hits
            if safe_text(hit.get("entity"))
        )
        reasons.append(f"watchlist_hit{f':{hit_names}' if hit_names else ''}")
        signal_details.append(
            {
                "signal": "watchlist_hit",
                "value": [hit.get("entity") for hit in watchlist_hits],
                "threshold": "any",
                "weight": weights["watchlist"],
                "score_component": round(watchlist_component, 2),
            }
        )

    promotion_score = round(score, 2)
    promotion_confidence = min(
        100,
        max(
            0,
            int(
                round(
                    promotion_score * 3
                    + len(supporting_signals) * 18
                    + (8 if has_portfolio_vertical else 0)
                    + (10 if best_entity and best_entity["source_diversity"] >= STRONG_ENTITY_SOURCE_DIVERSITY_THRESHOLD else 0)
                    + (3 if watchlist_hits else 0)
                )
            ),
        ),
    )

    reason_fields = {
        "signal_count": len(supporting_signals),
        "supporting_signals": supporting_signals,
        "promotion_score": promotion_score,
        "promotion_confidence": promotion_confidence,
        "signal_band": signal_band,
        "high_priority_source": has_high_priority_source,
        "portfolio_critical": has_portfolio_vertical,
        "explicit_override": has_override,
        "promotion_threshold": signal_threshold,
        "minimum_signal_count": DEFAULT_MIN_SIGNAL_COUNT,
        "signal_details": signal_details,
        "entity_evidence": entity_evidence,
        "input_excerpt": truncate_excerpt(item_text),
    }

    return {
        "promotion_score": promotion_score,
        "promotion_confidence": promotion_confidence,
        "signal_count": len(supporting_signals),
        "supporting_signals": supporting_signals,
        "has_high_priority_source": has_high_priority_source,
        "has_explicit_override": "explicit_high_priority_override" in supporting_signals,
        "has_strong_entity_reinforcement": "cross_source_entity_reinforcement" in supporting_signals,
        "has_source_diversity": "source_diversity" in supporting_signals,
        "has_high_signal_band": "high_signal_band" in supporting_signals,
        "has_portfolio_critical": "portfolio_critical" in supporting_signals,
        "signal_band": signal_band,
        "promotion_reasons": reasons,
        "promotion_reason_fields": reason_fields,
        "best_entity": best_entity,
    }


def truncate_excerpt(value, limit=240):
    text = normalize_whitespace(value)

    if len(text) <= limit:
        return text

    if limit <= 1:
        return text[:limit]

    return text[: limit - 1].rstrip() + "…"


def build_event_record(
    item,
    run_date,
    input_log_path,
    importance_threshold,
    include_slack_payloads,
    entity_contexts,
    weights,
):
    promotion_hash = get_promotion_hash(item)
    dedupe_hash = get_dedupe_hash(item)
    importance_score = get_importance_score(item)
    signal_band = build_signal_band(item)
    verticals = normalize_list(item.get("verticals"))
    tags = unique_tags(item)
    summary, preview = build_summary_and_preview(item)
    evidence = build_promotion_evidence(
        item,
        entity_contexts,
        weights,
        importance_threshold,
    )

    event_record = {
        "schema_version": 2,
        "event_type": "promote_to_hermes",
        "event_id": promotion_hash,
        "promotion_hash": promotion_hash,
        "emitted_at": datetime.now(UTC).isoformat(),
        "run_date": run_date,
        "source_log_path": str(input_log_path),
        "source_item_id": safe_text(item.get("item_id") or item.get("source_id")),
        "source_type": safe_text(item.get("source_type")),
        "source_name": safe_text(item.get("source_name") or "Unknown"),
        "source_domain": safe_text(item.get("source_domain")),
        "source_url": safe_text(item.get("source_url")),
        "subject": safe_text(item.get("subject")),
        "verticals": verticals,
        "tags": tags,
        "importance_score": importance_score,
        "promotion_threshold_override": item.get("promotion_threshold_override"),
        "dedupe_hash": dedupe_hash,
        "signal_band": signal_band,
        "watchlist_hits": item.get("watchlist_hits", []),
        "summary": summary,
        "preview": preview,
        "promotion_reasons": evidence["promotion_reasons"],
        "promotion_reason_fields": evidence["promotion_reason_fields"],
        "promotion_score": evidence["promotion_score"],
        "promotion_confidence": evidence["promotion_confidence"],
        "target_system": "hermes",
    }

    if include_slack_payloads:
        event_record["slack_notification"] = build_notification_payload(
            event_record["source_name"],
            signal_band,
            importance_score,
            evidence["promotion_confidence"],
            summary,
        )

    hermes_record = {
        "promotion_hash": promotion_hash,
        "promoted_at": event_record["emitted_at"],
        "run_date": run_date,
        "source_type": event_record["source_type"],
        "source_name": event_record["source_name"],
        "source_domain": event_record["source_domain"],
        "source_url": event_record["source_url"],
        "subject": event_record["subject"],
        "verticals": verticals,
        "tags": tags,
        "importance_score": importance_score,
        "promotion_threshold_override": item.get("promotion_threshold_override"),
        "dedupe_hash": dedupe_hash,
        "signal_band": signal_band,
        "watchlist_hits": item.get("watchlist_hits", []),
        "summary": summary,
        "preview": preview,
        "promotion_reasons": evidence["promotion_reasons"],
        "promotion_reason_fields": evidence["promotion_reason_fields"],
        "promotion_score": evidence["promotion_score"],
        "promotion_confidence": evidence["promotion_confidence"],
        "source_item_id": event_record["source_item_id"],
        "source_timestamp": safe_text(item.get("timestamp") or item.get("created_at")),
        "origin": "aeon",
    }

    if include_slack_payloads:
        hermes_record["slack_notification"] = event_record["slack_notification"]

    return {
        "promotion_hash": promotion_hash,
        "event_record": event_record,
        "hermes_record": hermes_record,
    }


def load_existing_hashes(folder):
    hashes = set()

    if not folder.exists():
        return hashes

    for path in sorted(folder.glob("*.jsonl")):
        for record in load_jsonl(path):
            for key in ("promotion_hash", "event_id", "dedupe_hash", "item_id"):
                value = safe_text(record.get(key))

                if value:
                    hashes.add(value)

    return hashes


def append_jsonl(path, records):
    if not records:
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def promote_items(
    input_log_path=DEFAULT_INPUT_LOG,
    event_dir=DEFAULT_EVENT_DIR,
    hermes_dir=DEFAULT_HERMES_DIR,
    run_date=None,
    importance_threshold=DEFAULT_IMPORTANCE_THRESHOLD,
    promotion_score_threshold=DEFAULT_PROMOTION_SCORE_THRESHOLD,
    promotion_confidence_threshold=DEFAULT_PROMOTION_CONFIDENCE_THRESHOLD,
    min_signal_count=DEFAULT_MIN_SIGNAL_COUNT,
    weights=None,
    dry_run=False,
    include_slack_payloads=False,
):
    input_log_path = Path(input_log_path)
    event_dir = Path(event_dir)
    hermes_dir = Path(hermes_dir)
    run_date = run_date or datetime.now(UTC).date().isoformat()
    weights = weights or DEFAULT_WEIGHTS

    items = load_jsonl(input_log_path)

    if not items:
        return {
            "input_count": 0,
            "selected_count": 0,
            "event_writes": 0,
            "hermes_writes": 0,
            "event_path": event_dir / f"{run_date}.jsonl",
            "hermes_path": hermes_dir / f"{run_date}.jsonl",
            "planned": [],
            "suppressed_count": 0,
            "metrics": {
                "promotion_score_threshold": promotion_score_threshold,
                "promotion_confidence_threshold": promotion_confidence_threshold,
                "min_signal_count": min_signal_count,
            },
        }

    existing_event_hashes = load_existing_hashes(event_dir)
    existing_hermes_hashes = load_existing_hashes(hermes_dir)
    entity_contexts = build_entity_context(items)

    planned = []
    event_records = []
    hermes_records = []
    suppressed_count = 0
    seen_narrative_signatures = set()

    for index, item in enumerate(items):
        item_text = build_item_text(item)
        narrative_signature = build_narrative_signature(item)
        suppression_reason = ""

        if narrative_signature in seen_narrative_signatures:
            suppression_reason = "duplicate_narrative"
        elif is_low_information_tweet(item, item_text):
            suppression_reason = "low_information_tweet"
        elif is_generic_market_commentary(item, item_text):
            suppression_reason = "generic_market_commentary"
        elif is_generic_hermes_term(item, item_text):
            suppression_reason = "generic_hermes_term"

        if suppression_reason:
            suppressed_count += 1
            continue

        seen_narrative_signatures.add(narrative_signature)
        evidence = build_promotion_evidence(
            item,
            entity_contexts[index],
            weights,
            importance_threshold,
        )
        signal_band = evidence["signal_band"]

        required_signals = (
            min_signal_count
            if not evidence["has_explicit_override"]
            else min(DEFAULT_MIN_SIGNAL_COUNT_WITH_OVERRIDE, min_signal_count)
        )

        if signal_band == "Normal Digest":
            if not (
                evidence["has_explicit_override"]
                or (
                    evidence["has_high_priority_source"]
                    and evidence["has_high_signal_band"]
                    and evidence["has_strong_entity_reinforcement"]
                )
            ):
                suppressed_count += 1
                continue

        if evidence["signal_count"] < required_signals:
            suppressed_count += 1
            continue

        if (
            evidence["promotion_confidence"] < promotion_confidence_threshold
            or evidence["promotion_score"] < get_effective_threshold(item, promotion_score_threshold)
        ):
            suppressed_count += 1
            continue

        promotion_hash = get_promotion_hash(item)

        if promotion_hash in existing_event_hashes and promotion_hash in existing_hermes_hashes:
            continue

        built = build_event_record(
            item,
            run_date,
            input_log_path,
            importance_threshold,
            include_slack_payloads,
            entity_contexts[index],
            weights,
        )

        built["event_record"]["promotion_reason_fields"]["promotion_threshold"] = get_effective_threshold(
            item,
            promotion_score_threshold,
        )
        built["event_record"]["promotion_reason_fields"]["promotion_confidence_threshold"] = promotion_confidence_threshold
        built["event_record"]["promotion_reason_fields"]["minimum_signal_count"] = min_signal_count
        built["hermes_record"]["promotion_reason_fields"]["promotion_threshold"] = get_effective_threshold(
            item,
            promotion_score_threshold,
        )
        built["hermes_record"]["promotion_reason_fields"]["promotion_confidence_threshold"] = promotion_confidence_threshold
        built["hermes_record"]["promotion_reason_fields"]["minimum_signal_count"] = min_signal_count

        planned.append(built)

        if promotion_hash not in existing_event_hashes:
            event_records.append(built["event_record"])
            existing_event_hashes.add(promotion_hash)

        if promotion_hash not in existing_hermes_hashes:
            hermes_records.append(built["hermes_record"])
            existing_hermes_hashes.add(promotion_hash)

    event_path = event_dir / f"{run_date}.jsonl"
    hermes_path = hermes_dir / f"{run_date}.jsonl"

    if not dry_run:
        append_jsonl(event_path, event_records)
        append_jsonl(hermes_path, hermes_records)

    return {
        "input_count": len(items),
        "selected_count": len(planned),
        "event_writes": len(event_records),
        "hermes_writes": len(hermes_records),
        "event_path": event_path,
        "hermes_path": hermes_path,
        "planned": planned,
        "suppressed_count": suppressed_count,
        "metrics": {
            "promotion_score_threshold": promotion_score_threshold,
            "promotion_confidence_threshold": promotion_confidence_threshold,
            "min_signal_count": min_signal_count,
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Promote high-signal AEON intake items into Hermes-oriented append-only logs."
    )
    parser.add_argument(
        "--input-log",
        default=str(DEFAULT_INPUT_LOG),
        help="Canonical processed intake log to read from.",
    )
    parser.add_argument(
        "--events-dir",
        default=str(DEFAULT_EVENT_DIR),
        help="Directory for append-only promotion events.",
    )
    parser.add_argument(
        "--hermes-dir",
        default=str(DEFAULT_HERMES_DIR),
        help="Directory for Hermes materialized promotion records.",
    )
    parser.add_argument(
        "--date",
        default="",
        help="Override the output partition date (YYYY-MM-DD). Defaults to UTC today.",
    )
    parser.add_argument(
        "--importance-threshold",
        default=DEFAULT_IMPORTANCE_THRESHOLD,
        type=int,
        help="Floor used to decide whether importance contributes a promotion signal.",
    )
    parser.add_argument(
        "--promotion-score-threshold",
        default=DEFAULT_PROMOTION_SCORE_THRESHOLD,
        type=float,
        help="Minimum weighted score required for Hermes promotion.",
    )
    parser.add_argument(
        "--promotion-confidence-threshold",
        default=DEFAULT_PROMOTION_CONFIDENCE_THRESHOLD,
        type=int,
        help="Minimum promotion confidence required for Hermes promotion.",
    )
    parser.add_argument(
        "--min-signal-count",
        default=DEFAULT_MIN_SIGNAL_COUNT,
        type=int,
        help="Minimum number of independent signals required for Hermes promotion.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate promotions without writing any JSONL output.",
    )
    parser.add_argument(
        "--include-slack-payloads",
        action="store_true",
        help="Attach Slack-safe notification payloads to the structured event output.",
    )

    args = parser.parse_args()

    result = promote_items(
        input_log_path=Path(args.input_log),
        event_dir=Path(args.events_dir),
        hermes_dir=Path(args.hermes_dir),
        run_date=args.date or None,
        importance_threshold=args.importance_threshold,
        promotion_score_threshold=args.promotion_score_threshold,
        promotion_confidence_threshold=args.promotion_confidence_threshold,
        min_signal_count=args.min_signal_count,
        dry_run=args.dry_run,
        include_slack_payloads=args.include_slack_payloads,
    )

    if result["input_count"] == 0:
        print("No processed intake log found.")
        raise SystemExit(0)

    if args.dry_run:
        print(
            "Dry run: {} promotions selected; {} event writes; {} Hermes writes.".format(
                result["selected_count"],
                result["event_writes"],
                result["hermes_writes"],
            )
        )
    else:
        print(
            "Promoted {} items; wrote {} event records and {} Hermes records.".format(
                result["selected_count"],
                result["event_writes"],
                result["hermes_writes"],
            )
        )
        print(f"Events: {result['event_path']}")
        print(f"Hermes: {result['hermes_path']}")


if __name__ == "__main__":
    main()
