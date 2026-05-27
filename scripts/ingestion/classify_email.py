import hashlib
import json
import sys
import re
from datetime import datetime, UTC
from email.utils import parseaddr
from pathlib import Path

import yaml

sys.path.append(str(Path(__file__).resolve().parents[1]))

from source_config import (
    find_source_entry,
    is_enabled,
    load_source_entries,
    merge_priority,
    merge_verticals,
    normalize_source_type,
    normalize_twitter_handle,
    priority_score_boost,
)
from utils.clean_text import clean_email_text


IGNORE_SUBJECT_PATTERNS = [
    "welcome",
    "complete your sign up",
    "confirm your email",
    "verify your email",
    "activate your account",
    "thanks for subscribing",
    "please confirm",
    "confirm subscription",
    "complete your signup"
]

GMAIL_LABEL_VERTICAL_PRIORS = {
    "Research/AI": ["AI"],
    "Research/RWA_Tokenization": ["RWA"],
    "Research/PrivateMarkets": ["RWA"],
    "Research/Macro": ["Macro"],
    "Research/Portfolio_Assets": ["Portfolio"],
    "Research/DeFi": ["DeFi"],
    "Research/Personal": ["Personal"]
}


def load_yaml(path):
    if not path.exists():
        return {}

    with path.open("r") as f:
        return yaml.safe_load(f) or {}


def safe_int(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_handle(value):
    return str(value or "").strip().lstrip("@").lower()


def infer_source_from_sender(sender):
    display_name, email = parseaddr(sender)
    domain = email.split("@")[-1].lower() if "@" in email else ""
    suggested_name = display_name.strip().replace('"', "")

    if not suggested_name and domain:
        suggested_name = (
            domain.split(".")[0]
            .replace("-", " ")
            .replace("_", " ")
            .title()
        )

    return domain, suggested_name


def load_email_registry():
    registry_path = Path("data/metadata/email_sources.json")

    if not registry_path.exists():
        return {}

    with registry_path.open("r") as f:
        return json.load(f)


def load_twitter_registry():
    config = load_yaml(Path("config/sources.yml"))
    registry = {}

    entries = config.get("sources") or config.get("twitter", []) or []

    for entry in entries:
        source_type = normalize_source_type(entry.get("source_type"), "twitter")

        if source_type != "twitter" and not entry.get("feed_url") and not entry.get("feed_urls"):
            continue

        handle = normalize_twitter_handle(entry)

        if not handle:
            continue

        registry[handle] = {
            "name": entry.get("source_name") or entry.get("name") or handle or "Unknown",
            "priority": entry.get("priority", "low"),
            "importance_score": safe_int(entry.get("importance_score", 1)),
            "verticals": entry.get("default_verticals") or entry.get("verticals", []) or []
        }

    return registry


def load_verticals():
    return load_yaml(Path("config/verticals.yml"))


def load_watchlist():
    path = Path("config/watchlist.yml")

    if not path.exists():
        return {}

    return load_yaml(path)


def normalize_match_values(value):
    if value in (None, ""):
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


def compile_watchlist_pattern(term, match_type):
    text = str(term or "").strip()

    if not text:
        return None

    if match_type == "regex":
        try:
            return re.compile(text, re.IGNORECASE)
        except re.error:
            return None

    if match_type == "phrase":
        pieces = [re.escape(piece) for piece in re.split(r"\s+", text) if piece]

        if not pieces:
            return None

        pattern = r"(?<!\w)" + r"\s+".join(pieces) + r"(?!\w)"
        return re.compile(pattern, re.IGNORECASE)

    escaped = re.escape(text)
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


def match_watchlist_terms(searchable_text, entity_data):
    matches = []
    explicit_match_types = (
        ("phrase_match", "phrase"),
        ("token_match", "token"),
        ("regex_match", "regex"),
    )

    for field_name, match_type in explicit_match_types:
        for term in normalize_match_values(entity_data.get(field_name)):
            pattern = compile_watchlist_pattern(term, match_type)

            if pattern and pattern.search(searchable_text):
                matches.append(term)

    if matches:
        return matches

    for term in normalize_match_values(entity_data.get("keywords")):
        pattern = compile_watchlist_pattern(term, "token")

        if pattern and pattern.search(searchable_text):
            matches.append(term)

    return matches


def existing_hashes(log_path):
    hashes = set()

    if not log_path.exists():
        return hashes

    for line in log_path.read_text().splitlines():
        if not line.strip():
            continue

        item = json.loads(line)
        item_id = item.get("item_id")
        dedupe_hash = item.get("dedupe_hash")

        if item_id:
            hashes.add(item_id)

        if dedupe_hash:
            hashes.add(dedupe_hash)

    return hashes


def parse_email_message(path):
    metadata = {
        "source_type": "email_manual",
        "source_name": "Unknown",
        "source_domain": "",
        "known_source": "False",
        "sender": "",
        "subject": "",
        "priority": "low",
        "importance_score": 1,
        "gmail_label": "",
        "source_id": path.stem,
        "source_file": str(path),
        "content": ""
    }

    body_lines = []

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("SOURCE:"):
            metadata["source_name"] = line.replace("SOURCE:", "").strip()
        elif line.startswith("SOURCE_DOMAIN:"):
            metadata["source_domain"] = line.replace(
                "SOURCE_DOMAIN:",
                ""
            ).strip()
        elif line.startswith("KNOWN_SOURCE:"):
            metadata["known_source"] = line.replace(
                "KNOWN_SOURCE:",
                ""
            ).strip()
        elif line.startswith("SENDER:"):
            metadata["sender"] = line.replace("SENDER:", "").strip()
        elif line.startswith("SUBJECT:"):
            metadata["subject"] = line.replace("SUBJECT:", "").strip()
        elif line.startswith("PRIORITY:"):
            metadata["priority"] = line.replace("PRIORITY:", "").strip()
        elif line.startswith("GMAIL_LABEL:"):
            metadata["gmail_label"] = line.replace("GMAIL_LABEL:", "").strip()
        elif line.startswith("IMPORTANCE_SCORE:"):
            metadata["importance_score"] = safe_int(
                line.replace("IMPORTANCE_SCORE:", "").strip()
            )
        else:
            body_lines.append(line)

    metadata["content"] = " ".join(body_lines).strip()
    return metadata


def load_jsonl_records(folder, source_type):
    records = []

    if not folder.exists():
        return records

    for path in sorted(folder.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue

            raw = json.loads(line)

            if not isinstance(raw, dict):
                continue

            raw.setdefault("source_type", source_type)
            raw.setdefault("source_file", str(path))
            records.append(raw)

    return records


def build_raw_items():
    items = []

    email_folder = Path("data/intake/email")
    pdf_folder = Path("data/intake/pdf")
    twitter_folder = Path("data/intake/twitter")

    if email_folder.exists():
        for path in sorted(email_folder.glob("*.txt")):
            items.append(parse_email_message(path))

    items.extend(load_jsonl_records(pdf_folder, "pdf"))
    items.extend(load_jsonl_records(twitter_folder, "twitter"))

    return items


def enrich_metadata(raw_item, email_registry, twitter_registry, source_entries):
    source_type = str(raw_item.get("source_type") or "email_manual").lower()
    source_name = raw_item.get("source_name") or "Unknown"
    priority = raw_item.get("priority", "low")
    importance_score = safe_int(raw_item.get("importance_score", 1))
    source_verticals = list(raw_item.get("verticals") or [])
    source_domain = raw_item.get("source_domain", "")
    known_source = str(raw_item.get("known_source", "False"))
    source_watchlist_boost = safe_int(raw_item.get("watchlist_boost"), 0)
    source_promotion_threshold_override = raw_item.get("promotion_threshold_override")
    source_digest_enabled = is_enabled(raw_item, "digest_enabled", True)
    source_alert_enabled = is_enabled(raw_item, "alert_enabled", True)

    if source_type.startswith("email"):
        sender = raw_item.get("sender", "")
        domain, suggested_name = infer_source_from_sender(sender)

        if domain:
            source_domain = domain

        if not source_name or source_name == "Unknown":
            source_name = suggested_name or "Unknown"

        for registered_domain, metadata in email_registry.items():
            if registered_domain.lower() in sender.lower():
                source_name = metadata.get("name", source_name)
                priority = metadata.get("priority", priority)
                importance_score = safe_int(
                    metadata.get("importance_score", importance_score),
                    importance_score
                )
                source_verticals = merge_verticals(
                    source_verticals,
                    metadata.get("default_verticals", []) or []
                )
                known_source = "True"
                break

    elif source_type == "twitter":
        handle = normalize_handle(
            raw_item.get("source_handle")
            or raw_item.get("author_handle")
            or raw_item.get("handle")
            or raw_item.get("username")
        )

        if handle and handle in twitter_registry:
            metadata = twitter_registry[handle]
            source_name = metadata.get("name", source_name)
            priority = metadata.get("priority", priority)
            importance_score = safe_int(
                metadata.get("importance_score", importance_score),
                importance_score
            )
            source_verticals = merge_verticals(
                source_verticals,
                metadata.get("verticals", []) or []
            )
            known_source = "True"
        elif raw_item.get("source_name"):
            source_name = raw_item["source_name"]

    elif source_type == "pdf":
        if raw_item.get("source_name"):
            source_name = raw_item["source_name"]

    if raw_item.get("verticals"):
        source_verticals = list(raw_item.get("verticals") or [])

    if raw_item.get("priority"):
        priority = raw_item["priority"]

    if raw_item.get("importance_score") is not None:
        importance_score = safe_int(raw_item.get("importance_score"), importance_score)

    source_config = find_source_entry(raw_item, source_entries or [])

    if source_config:
        source_name = source_config.get("source_name") or source_name
        priority = merge_priority(priority, source_config.get("priority", priority))
        importance_score = max(
            importance_score,
            safe_int(source_config.get("importance_score", importance_score), importance_score)
        )
        source_verticals = merge_verticals(
            source_verticals,
            source_config.get("default_verticals", []) or []
        )
        source_watchlist_boost = safe_int(source_config.get("watchlist_boost"), 0)
        source_promotion_threshold_override = source_config.get(
            "promotion_threshold_override"
        )
        source_digest_enabled = is_enabled(source_config, "digest_enabled", True)
        source_alert_enabled = is_enabled(source_config, "alert_enabled", True)
        known_source = "True"

    if source_config and source_config.get("priority"):
        importance_score += priority_score_boost(source_config.get("priority"))

    return {
        "source_type": source_type,
        "source_name": source_name or "Unknown",
        "priority": priority,
        "importance_score": importance_score,
        "source_verticals": source_verticals,
        "source_domain": source_domain,
        "known_source": known_source,
        "watchlist_boost": source_watchlist_boost,
        "promotion_threshold_override": source_promotion_threshold_override,
        "digest_enabled": source_digest_enabled,
        "alert_enabled": source_alert_enabled,
    }


def normalize_content(raw_item):
    content = (
        raw_item.get("content")
        or raw_item.get("text")
        or raw_item.get("body")
        or raw_item.get("raw_text")
        or raw_item.get("content_preview")
        or ""
    )

    content = clean_email_text(str(content))

    if content:
        return content

    return clean_email_text(str(raw_item.get("subject", "")))


def source_identity(raw_item):
    return (
        raw_item.get("source_id")
        or raw_item.get("id")
        or raw_item.get("tweet_id")
        or raw_item.get("message_id")
        or raw_item.get("source_file")
        or raw_item.get("source_name")
        or "unknown"
    )


def classify_item(
    raw_item,
    email_registry,
    twitter_registry,
    verticals,
    watchlist,
    seen,
    source_entries=None,
):
    metadata = enrich_metadata(
        raw_item,
        email_registry,
        twitter_registry,
        source_entries if source_entries is not None else load_source_entries(),
    )

    subject = str(raw_item.get("subject") or "").strip()
    content = normalize_content(raw_item)

    if not content.strip():
        return None

    if any(pattern in subject.lower() for pattern in IGNORE_SUBJECT_PATTERNS):
        return None

    normalized_content = content.lower().strip()
    searchable_text = f"{subject} {content}"

    item_id = hashlib.sha256(
        normalized_content.encode("utf-8")
    ).hexdigest()[:16]
    dedupe_hash = item_id

    if item_id in seen or dedupe_hash in seen:
        return None

    scores = {}

    for vertical, data in verticals.items():
        keywords = data.get("keywords", []) or []
        score = 0

        for keyword in keywords:
            score += normalized_content.count(str(keyword).lower())

        scores[vertical] = score

    for vertical in metadata["source_verticals"]:
        scores[vertical] = scores.get(vertical, 0) + 3

    gmail_label = str(raw_item.get("gmail_label", "")).strip()
    label_verticals = GMAIL_LABEL_VERTICAL_PRIORS.get(gmail_label, [])

    for vertical in label_verticals:
        scores[vertical] = scores.get(vertical, 0) + 3

    if metadata["known_source"] == "True":
        for vertical in label_verticals or metadata["source_verticals"]:
            scores[vertical] = scores.get(vertical, 0) + 1

    watchlist_hits = []

    for entity_name, entity_data in watchlist.get("entities", {}).items():
        entity_verticals = entity_data.get("verticals", []) or []
        score_boost = safe_int(entity_data.get("score_boost", 0), 0)
        matched_keywords = match_watchlist_terms(searchable_text, entity_data)

        if not matched_keywords:
            continue

        watchlist_hits.append({
            "entity": entity_name,
            "matched_keywords": matched_keywords,
            "score_boost": score_boost
        })

        for vertical in entity_verticals:
            scores[vertical] = scores.get(vertical, 0) + score_boost

        metadata["importance_score"] += score_boost

        if metadata["importance_score"] >= 8:
            metadata["priority"] = "high"
        elif metadata["importance_score"] >= 4:
            metadata["priority"] = "medium"

    if watchlist_hits and metadata.get("watchlist_boost"):
        metadata["importance_score"] += safe_int(metadata.get("watchlist_boost"), 0)

    matched_verticals = [
        vertical for vertical, score in scores.items()
        if score >= 2
    ]

    importance_score = metadata["importance_score"]
    priority = metadata["priority"]

    if importance_score >= 8:
        priority = "high"
    elif importance_score >= 4 and priority == "low":
        priority = "medium"

    record = {
        "item_id": item_id,
        "dedupe_hash": dedupe_hash,
        "timestamp": datetime.now(UTC).isoformat(),
        "source_type": metadata["source_type"],
        "source_file": str(raw_item.get("source_file", "")),
        "source_id": source_identity(raw_item),
        "source_name": metadata["source_name"],
        "source_domain": metadata["source_domain"],
        "known_source": metadata["known_source"],
        "sender": raw_item.get("sender", ""),
        "source_handle": raw_item.get("source_handle", ""),
        "source_url": raw_item.get("source_url", ""),
        "subject": subject,
        "priority": priority,
        "importance_score": importance_score,
        "gmail_label": gmail_label,
        "verticals": matched_verticals,
        "scores": scores,
        "watchlist_hits": watchlist_hits,
        "watchlist_boost": metadata.get("watchlist_boost", 0),
        "promotion_threshold_override": metadata.get("promotion_threshold_override"),
        "digest_enabled": metadata.get("digest_enabled", True),
        "alert_enabled": metadata.get("alert_enabled", True),
        "content_preview": content[:200]
    }

    if raw_item.get("pdf_title"):
        record["pdf_title"] = raw_item["pdf_title"]

    if raw_item.get("page_count") is not None:
        record["page_count"] = raw_item["page_count"]

    if raw_item.get("author_handle"):
        record["author_handle"] = raw_item["author_handle"]

    if raw_item.get("created_at"):
        record["created_at"] = raw_item["created_at"]

    if raw_item.get("raw_text"):
        record["raw_text"] = raw_item["raw_text"]

    return record


def main():
    log_path = Path("data/processed/intake_log.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)

    email_registry = load_email_registry()
    twitter_registry = load_twitter_registry()
    source_entries = load_source_entries()
    verticals = load_verticals()
    watchlist = load_watchlist()
    seen = existing_hashes(log_path)
    raw_items = build_raw_items()

    if not raw_items:
        print("No intake files found.")
        raise SystemExit(0)

    records = []

    for raw_item in raw_items:
        record = classify_item(
            raw_item,
            email_registry,
            twitter_registry,
            verticals,
            watchlist,
            seen,
            source_entries,
        )

        if not record:
            continue

        seen.add(record["item_id"])
        seen.add(record["dedupe_hash"])
        records.append(record)

    with log_path.open("a") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    for record in records:
        print(
            f"Processed: {record['source_type']} "
            f"{record['source_id']} -> {record['verticals']}"
        )


if __name__ == "__main__":
    main()
