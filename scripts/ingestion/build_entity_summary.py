import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, date, time
from pathlib import Path

import yaml


DEFAULT_LOG_PATH = Path("data/processed/intake_log.jsonl")
DEFAULT_OUTPUT_PATH = Path("data/processed/entity_summary.json")
DEFAULT_ENTITY_DIR = Path("data/processed/entities")
DEFAULT_ENTITIES_PATH = Path("config/entities.yml")
DEFAULT_WATCHLIST_PATH = Path("config/watchlist.yml")
DEFAULT_SOURCES_PATH = Path("config/sources.yml")
MAX_ENTITY_FILENAME_LENGTH = 120
ENTITY_FILENAME_EXTENSION = ".json"

ALLOWED_SOURCE_TYPES = {"twitter", "pdf", "newsletter"}
ENTITY_SECTION_TITLES = {
    "Top Emerging Entities",
    "Most-mentioned Entities",
    "Cross-source Entities",
}

TOKEN_RE = re.compile(r"[#$@]?[A-Za-z0-9][A-Za-z0-9&.'/_:-]*")
TRAILING_PUNCT_RE = re.compile(r"^[\W_]+|[\W_]+$")
GENERIC_STOPWORDS = {
    "about",
    "and",
    "article",
    "brief",
    "daily",
    "digest",
    "email",
    "feed",
    "followup",
    "for",
    "from",
    "gmail",
    "market",
    "markets",
    "news",
    "newsletter",
    "note",
    "notes",
    "pdf",
    "post",
    "preview",
    "report",
    "research",
    "roundup",
    "source",
    "story",
    "summary",
    "thread",
    "today",
    "twitter",
    "update",
    "weekly",
}
ENTITY_SUPPRESSION_WORDS = GENERIC_STOPWORDS | {
    "a",
    "an",
    "he",
    "here",
    "if",
    "i",
    "it",
    "now",
    "rt",
    "she",
    "the",
    "they",
    "this",
    "today",
    "we",
    "you",
}
SHORT_ENTITY_ALLOWLIST = {
    "ai": "AI",
    "btc": "BTC",
    "eth": "ETH",
    "rwa": "RWA",
    "vc": "VC",
    "zk": "ZK",
}
CONNECTORS = {"of", "the", "in", "on", "at", "de", "la", "van", "von"}
LEADING_ARTICLES = {"the", "a", "an"}


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clean_text(value):
    text = str(value or "")
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_source_type(source_type):
    source_type = str(source_type or "").strip().lower()

    if not source_type:
        return ""

    if source_type == "twitter":
        return "twitter"

    if source_type == "pdf":
        return "pdf"

    if source_type == "newsletter" or source_type.startswith("email"):
        return "newsletter"

    return ""


def parse_timestamp(value):
    text = clean_text(value)

    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text[:10])
            parsed = datetime.combine(parsed_date, time.min)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)

    return parsed.astimezone(UTC)


def item_timestamp(item):
    for key in ("timestamp", "created_at", "posted_at", "published_at", "date"):
        parsed = parse_timestamp(item.get(key))

        if parsed is not None:
            return parsed

    return None


def item_id(item, fallback_index):
    return (
        item.get("item_id")
        or item.get("id")
        or item.get("hash")
        or item.get("dedupe_hash")
        or item.get("source_id")
        or f"item-{fallback_index}"
    )


def item_source_name(item):
    return clean_text(
        item.get("source_name")
        or item.get("source")
        or item.get("source_handle")
        or item.get("author_handle")
        or "Unknown"
    )


def item_source_type(item):
    return normalize_source_type(item.get("source_type"))


def item_verticals(item):
    verticals = item.get("verticals") or item.get("source_verticals") or []

    if not isinstance(verticals, list):
        verticals = [verticals]

    cleaned = []
    seen = set()

    for vertical in verticals:
        value = clean_text(vertical)

        if not value or value in seen:
            continue

        seen.add(value)
        cleaned.append(value)

    return cleaned


def item_importance_score(item):
    return safe_int(item.get("importance_score"), 1)


def is_digest_enabled(item):
    value = item.get("digest_enabled", True)

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() not in {"false", "0", "no", "off"}


def extract_item_text(item):
    parts = []

    for key in (
        "subject",
        "source_name",
        "summary",
        "content_preview",
        "content",
        "raw_text",
        "body",
        "text",
        "title",
        "pdf_title",
    ):
        value = clean_text(item.get(key))

        if value:
            parts.append(value)

    return clean_text(" ".join(parts))


def clean_token(token):
    token = clean_text(token)

    if not token:
        return ""

    token = token.lstrip("@#$")
    token = TRAILING_PUNCT_RE.sub("", token)

    lowered = token.lower()

    if lowered in SHORT_ENTITY_ALLOWLIST:
        return SHORT_ENTITY_ALLOWLIST[lowered]

    return token.strip()


def normalize_entity_type(value):
    entity_type = re.sub(r"[^a-z0-9]+", "_", clean_text(value).lower()).strip("_")
    return entity_type or "unknown"


def normalize_flag(value, default=False):
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    return str(value).strip().lower() not in {"", "0", "false", "no", "off", "none"}


def normalize_entity_list(value):
    if value is None:
        return []

    if not isinstance(value, list):
        value = [value]

    cleaned = []
    seen = set()

    for item in value:
        text = clean_text(item)

        if not text or text in seen:
            continue

        seen.add(text)
        cleaned.append(text)

    return cleaned


def resolve_entity_alias(alias, alias_index):
    alias_key = entity_key(alias)

    if not alias_key:
        return None

    return alias_index.get(alias_key)


def build_entity_candidate(spec, match_start, match_confidence, matched_alias):
    return {
        "entity_key": spec["entity_key"],
        "entity_name": spec["entity_name"],
        "entity_type": spec["entity_type"],
        "entity_confidence": round(match_confidence, 2),
        "position": match_start,
        "priority": spec["priority"],
        "matched_alias": matched_alias,
    }


def legacy_entity_spec(entity_name, entity_data):
    aliases = normalize_entity_list(entity_data.get("token_match") or [])
    aliases.extend(alias for alias in normalize_entity_list(entity_data.get("phrase_match") or []) if alias not in aliases)

    return {
        "entity_name": entity_name,
        "entity_key": entity_key(entity_name),
        "entity_type": normalize_entity_type(entity_data.get("type") or "watchlist"),
        "verticals": normalize_entity_list(entity_data.get("verticals") or []),
        "priority": safe_int(entity_data.get("score_boost"), 0),
        "watchlist_enabled": True,
        "watchlist_boost": safe_int(entity_data.get("score_boost"), 0),
        "aliases": aliases,
        "regexes": normalize_entity_list(entity_data.get("regex_match") or []),
    }


def build_entity_spec(entity_name, entity_data, *, default_priority=0, default_type="entity"):
    entity_name = clean_text(entity_name)

    if not entity_name:
        return None

    aliases = normalize_entity_list(entity_data.get("aliases") or [])
    if entity_name not in aliases:
        aliases.insert(0, entity_name)

    alias_records = []

    for alias in aliases:
        pattern = build_entity_pattern(alias)

        if pattern is None:
            continue

        alias_records.append(
            {
                "alias": alias,
                "alias_key": entity_key(alias),
                "pattern": pattern,
                "confidence": 1.0 if entity_key(alias) == entity_key(entity_name) else 0.96,
            }
        )

    regexes = entity_data.get("regexes") or []

    if not isinstance(regexes, list):
        regexes = [regexes]

    for regex in regexes:
        regex_text = clean_text(regex)

        if not regex_text:
            continue

        try:
            alias_records.append(
                {
                    "alias": regex_text,
                    "alias_key": entity_key(regex_text),
                    "pattern": re.compile(regex_text, re.IGNORECASE),
                    "confidence": 0.96,
                }
            )
        except re.error:
            continue

    return {
        "entity_name": entity_name,
        "entity_key": entity_key(entity_name),
        "entity_type": normalize_entity_type(entity_data.get("type") or default_type),
        "verticals": normalize_entity_list(entity_data.get("verticals") or []),
        "priority": safe_int(entity_data.get("priority"), default_priority),
        "watchlist_enabled": normalize_flag(entity_data.get("watchlist_enabled"), True),
        "watchlist_boost": safe_int(
            entity_data.get("watchlist_boost"),
            safe_int(entity_data.get("priority"), default_priority),
        ),
        "aliases": aliases,
        "alias_records": alias_records,
    }


def token_is_entity(token):
    token = clean_token(token)

    if not token:
        return False, 0

    lowered = token.lower()

    if lowered in SHORT_ENTITY_ALLOWLIST:
        return True, 2.0

    if len(token) < 3:
        return False, 0

    if lowered in ENTITY_SUPPRESSION_WORDS:
        return False, 0

    if lowered in CONNECTORS:
        return False, 0

    if token.isupper() and len(token) >= 2:
        return True, 2.0

    if any(char.isdigit() for char in token) and any(char.isalpha() for char in token):
        return True, 1.9

    if any(char.isupper() for char in token[1:]) and any(char.islower() for char in token):
        return True, 1.8

    if token[0].isupper() and token[1:].islower():
        return True, 1.4

    return False, 0


def canonicalize_phrase(tokens):
    return " ".join(clean_token(token) for token in tokens if clean_token(token))


def entity_key(phrase):
    return re.sub(r"[^a-z0-9]+", " ", phrase.lower()).strip()


def load_yaml_file(path):
    path = Path(path)

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def build_entity_pattern(alias):
    alias = clean_token(alias)

    if not alias:
        return None

    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def load_configured_entities(
    entities_path=DEFAULT_ENTITIES_PATH,
    watchlist_path=DEFAULT_WATCHLIST_PATH,
    sources_path=DEFAULT_SOURCES_PATH,
):
    configured_entities = {}

    entities_data = load_yaml_file(entities_path)
    entity_specs = entities_data.get("entities") or {}

    if not entity_specs:
        watchlist_data = load_yaml_file(watchlist_path)
        entity_specs = watchlist_data.get("entities") or {}

    for entity_name, entity_data in entity_specs.items():
        if "aliases" in entity_data or "type" in entity_data:
            spec = build_entity_spec(
                entity_name,
                entity_data,
                default_priority=entity_data.get("priority", 0),
                default_type=entity_data.get("type", "entity"),
            )
        else:
            legacy_spec = legacy_entity_spec(entity_name, entity_data)
            spec = build_entity_spec(
                legacy_spec["entity_name"],
                legacy_spec,
                default_priority=legacy_spec["priority"],
                default_type=legacy_spec["entity_type"],
            )
            spec["alias_records"] = []

            for alias in legacy_spec["aliases"]:
                pattern = build_entity_pattern(alias)

                if pattern is not None:
                    spec["alias_records"].append(
                        {
                            "alias": alias,
                            "alias_key": entity_key(alias),
                            "pattern": pattern,
                            "confidence": 0.96 if entity_key(alias) != spec["entity_key"] else 1.0,
                        }
                    )

            for regex in legacy_spec["regexes"]:
                try:
                    spec["alias_records"].append(
                        {
                            "alias": regex,
                            "alias_key": entity_key(regex),
                            "pattern": re.compile(regex, re.IGNORECASE),
                            "confidence": 0.96,
                        }
                    )
                except re.error:
                    continue

        if spec is None:
            continue

        entry = configured_entities.setdefault(
            spec["entity_key"],
            {
                "entity_name": spec["entity_name"],
                "entity_key": spec["entity_key"],
                "entity_type": spec["entity_type"],
                "verticals": list(spec["verticals"]),
                "priority": spec["priority"],
                "watchlist_enabled": spec["watchlist_enabled"],
                "watchlist_boost": spec["watchlist_boost"],
                "aliases": [],
                "alias_records": [],
            },
        )

        if spec["priority"] > entry["priority"] or (
            spec["priority"] == entry["priority"]
            and spec["entity_name"].lower() < entry["entity_name"].lower()
        ):
            entry["entity_name"] = spec["entity_name"]
            entry["entity_type"] = spec["entity_type"]
            entry["watchlist_enabled"] = spec["watchlist_enabled"]
            entry["watchlist_boost"] = spec["watchlist_boost"]

        entry["priority"] = max(entry["priority"], spec["priority"])
        entry["verticals"] = list(dict.fromkeys(entry["verticals"] + spec["verticals"]))
        entry["aliases"] = list(dict.fromkeys(entry["aliases"] + spec["aliases"]))
        entry["alias_records"].extend(spec["alias_records"])

    sources_data = load_yaml_file(sources_path)
    for source_entry in sources_data.get("sources") or []:
        source_name = clean_text(source_entry.get("source_name"))

        if not source_name:
            continue

        entry = configured_entities.setdefault(
            entity_key(source_name),
            {
                "entity_name": source_name,
                "entity_key": entity_key(source_name),
                "entity_type": "source",
                "verticals": [],
                "priority": 0,
                "watchlist_enabled": False,
                "watchlist_boost": 0,
                "aliases": [],
                "alias_records": [],
            },
        )

        entry["entity_name"] = source_name
        entry["entity_type"] = "source"
        entry["priority"] = max(entry["priority"], 2)

        pattern = build_entity_pattern(source_name)

        if pattern is not None:
            entry["alias_records"].append(
                {
                    "alias": source_name,
                    "alias_key": entity_key(source_name),
                    "pattern": pattern,
                    "confidence": 1.0,
                }
            )

    return list(configured_entities.values())


def candidate_is_valid(phrase):
    phrase = clean_text(phrase)

    if not phrase:
        return False

    lowered = phrase.lower()

    if lowered in SHORT_ENTITY_ALLOWLIST:
        return True

    if len(phrase) < 3:
        return False

    if lowered in ENTITY_SUPPRESSION_WORDS:
        return False

    return True


def extract_configured_entities(text, configured_entities):
    candidates = []

    for spec in configured_entities:
        best_candidate = None

        for alias_record in spec["alias_records"]:
            match = alias_record["pattern"].search(text)

            if match is None:
                continue

            candidate = build_entity_candidate(
                spec,
                match.start(),
                alias_record["confidence"],
                alias_record["alias"],
            )

            if best_candidate is None:
                best_candidate = candidate
                continue

            if candidate["entity_confidence"] > best_candidate["entity_confidence"]:
                best_candidate = candidate
                continue

            if (
                candidate["entity_confidence"] == best_candidate["entity_confidence"]
                and candidate["position"] < best_candidate["position"]
            ):
                best_candidate = candidate

        if best_candidate is None:
            continue

        if not candidate_is_valid(best_candidate["entity_name"]):
            continue

        candidates.append(best_candidate)

    return candidates


def unknown_entity_confidence(token_score, strong_tokens, phrase):
    if strong_tokens >= 2:
        return 0.84

    if token_score >= 1.95:
        return 0.96

    if token_score >= 1.8:
        return 0.9

    if token_score >= 1.4:
        return 0.72

    if len(phrase.split()) >= 2:
        return 0.8

    return 0.6


def extract_entities(text, configured_entities=None):
    text = clean_text(text)

    if not text:
        return []

    if configured_entities is None:
        configured_entities = load_configured_entities()

    tokens = [match.group(0) for match in TOKEN_RE.finditer(text)]
    candidates = []
    alias_index = {}

    for spec in sorted(
        configured_entities,
        key=lambda entry: (-entry["priority"], entry["entity_name"].lower()),
    ):
        alias_index.setdefault(spec["entity_key"], spec)

        for alias_record in spec["alias_records"]:
            alias_index.setdefault(alias_record["alias_key"], spec)

    candidates.extend(extract_configured_entities(text, configured_entities))
    index = 0

    while index < len(tokens):
        token = tokens[index]
        is_entity, token_score = token_is_entity(token)
        lowered = clean_token(token).lower()

        if lowered in SHORT_ENTITY_ALLOWLIST:
            canonical_token = clean_token(token)
            resolved = resolve_entity_alias(canonical_token, alias_index)

            if resolved is not None:
                match_confidence = 1.0 if entity_key(canonical_token) == resolved["entity_key"] else 0.96
                candidates.append(build_entity_candidate(resolved, index, match_confidence, canonical_token))
            else:
                candidates.append(
                    {
                        "entity_key": entity_key(canonical_token),
                        "entity_name": canonical_token,
                        "entity_type": "unknown",
                        "entity_confidence": 1.0,
                        "position": index,
                        "priority": 1,
                        "matched_alias": canonical_token,
                    }
                )
            index += 1
            continue

        if lowered in LEADING_ARTICLES and index + 1 < len(tokens):
            next_is_entity, _ = token_is_entity(tokens[index + 1])

            if next_is_entity:
                start = index
                end = index + 2

                while end < len(tokens):
                    next_token = tokens[end]
                    next_clean = clean_token(next_token).lower()
                    next_is_entity, _ = token_is_entity(next_token)

                    if next_clean in SHORT_ENTITY_ALLOWLIST:
                        break

                    if next_is_entity or next_clean in CONNECTORS:
                        end += 1
                        continue

                    break

                phrase_tokens = tokens[start:end]
                phrase = canonicalize_phrase(phrase_tokens)

                if phrase and candidate_is_valid(phrase):
                    if len(phrase_tokens) == 2 and clean_token(phrase_tokens[1]).lower() in SHORT_ENTITY_ALLOWLIST:
                        index += 1
                        continue

                    resolved = resolve_entity_alias(phrase, alias_index)

                    if resolved is not None:
                        match_confidence = 1.0 if entity_key(phrase) == resolved["entity_key"] else 0.96
                        candidates.append(build_entity_candidate(resolved, start, match_confidence, phrase))
                    else:
                        candidates.append(
                            {
                                "entity_key": entity_key(phrase),
                                "entity_name": phrase,
                                "entity_type": "unknown",
                                "entity_confidence": unknown_entity_confidence(
                                    1.4,
                                    len([token for token in phrase_tokens if token_is_entity(token)[0]]),
                                    phrase,
                                ),
                                "position": start,
                                "priority": 1,
                                "matched_alias": phrase,
                            }
                        )

                index = end
                continue

        if not is_entity:
            index += 1
            continue

        start = index
        end = index + 1
        strong_tokens = 1
        score = token_score

        while end < len(tokens):
            next_token = tokens[end]
            next_clean = clean_token(next_token).lower()
            next_is_entity, next_score = token_is_entity(next_token)

            if next_clean in SHORT_ENTITY_ALLOWLIST:
                break

            if next_is_entity:
                strong_tokens += 1
                score += next_score
                end += 1
                continue

            if next_clean in CONNECTORS:
                score += 0.1
                end += 1
                continue

            break

        phrase_tokens = tokens[start:end]
        phrase = canonicalize_phrase(phrase_tokens)

        if phrase and candidate_is_valid(phrase) and (strong_tokens >= 2 or score >= 1.3):
            resolved = resolve_entity_alias(phrase, alias_index)

            if resolved is not None:
                match_confidence = 1.0 if entity_key(phrase) == resolved["entity_key"] else 0.96
                candidates.append(build_entity_candidate(resolved, start, match_confidence, phrase))
            else:
                candidates.append(
                    {
                        "entity_key": entity_key(phrase),
                        "entity_name": phrase,
                        "entity_type": "unknown",
                        "entity_confidence": unknown_entity_confidence(score, strong_tokens, phrase),
                        "position": start,
                        "priority": 1,
                        "matched_alias": phrase,
                    }
                )

        index = end if end > index else index + 1

    deduped = {}

    for candidate in sorted(
        candidates,
        key=lambda entry: (
            -entry.get("priority", 1),
            -entry.get("entity_confidence", 0),
            entry["position"],
            entry["entity_name"].lower(),
        ),
    ):
        key = candidate["entity_key"]

        if key in deduped:
            continue

        deduped[key] = candidate

    return [
        {
            "entity_key": candidate["entity_key"],
            "entity_name": candidate["entity_name"],
            "entity_type": candidate["entity_type"],
            "entity_confidence": candidate["entity_confidence"],
            "position": candidate["position"],
        }
        for candidate in deduped.values()
    ]


def select_source_bucket(item):
    source_type = item_source_type(item)

    if source_type in ALLOWED_SOURCE_TYPES:
        return source_type

    return ""


def load_items(log_path):
    log_path = Path(log_path)

    if not log_path.exists():
        return []

    items = []

    for index, raw_line in enumerate(log_path.read_text(encoding="utf-8").splitlines()):
        line = raw_line.strip()

        if not line:
            continue

        item = json.loads(line)

        if isinstance(item, dict):
            item["_input_index"] = index
            items.append(item)

    return items


def build_entity_summary(
    log_path=DEFAULT_LOG_PATH,
    output_path=DEFAULT_OUTPUT_PATH,
    entity_dir=DEFAULT_ENTITY_DIR,
    entities_path=DEFAULT_ENTITIES_PATH,
    watchlist_path=DEFAULT_WATCHLIST_PATH,
    sources_path=DEFAULT_SOURCES_PATH,
):
    log_path = Path(log_path)
    output_path = Path(output_path)
    entity_dir = Path(entity_dir)
    entity_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    items = load_items(log_path)
    aggregates = {}
    configured_entities = load_configured_entities(entities_path, watchlist_path, sources_path)

    for fallback_index, item in enumerate(items):
        if not is_digest_enabled(item):
            continue

        source_bucket = select_source_bucket(item)

        if not source_bucket:
            continue

        text = extract_item_text(item)
        entities = extract_entities(text, configured_entities=configured_entities)

        if not entities:
            continue

        item_ts = item_timestamp(item)
        importance_score = item_importance_score(item)
        source_name = item_source_name(item)
        source_type = source_bucket
        verticals = item_verticals(item)
        unique_entities = []
        seen_keys = set()

        for entity in entities:
            entity_key_value = entity["entity_key"]

            if entity_key_value in seen_keys:
                continue

            seen_keys.add(entity_key_value)
            unique_entities.append(entity)

        for entity in unique_entities:
            key = entity["entity_key"]
            aggregate = aggregates.setdefault(
                key,
                {
                    "entity_key": key,
                    "entity_name": entity["entity_name"],
                    "entity_type": entity.get("entity_type", "unknown"),
                    "mention_count": 0,
                    "confidence_total": 0.0,
                    "source_names": set(),
                    "source_types": set(),
                    "importance_total": 0,
                    "latest_mention_timestamp": None,
                    "latest_mention_item_id": "",
                    "latest_mention_source": "",
                    "latest_mention_subject": "",
                    "latest_mention_preview": "",
                    "vertical_counts": Counter(),
                    "mentions": [],
                    "first_seen_index": entity["position"],
                },
            )

            if not aggregate["entity_name"]:
                aggregate["entity_name"] = entity["entity_name"]

            entity_type = entity.get("entity_type", "unknown")

            if aggregate["entity_type"] == "unknown" and entity_type != "unknown":
                aggregate["entity_type"] = entity_type

            aggregate["mention_count"] += 1
            aggregate["confidence_total"] += entity.get("entity_confidence", 0.0)
            aggregate["source_names"].add(source_name)
            aggregate["source_types"].add(source_type)
            aggregate["importance_total"] += importance_score

            if verticals:
                aggregate["vertical_counts"].update(verticals)

            mention_record = {
                "item_id": item_id(item, fallback_index),
                "source_name": source_name,
                "source_type": source_type,
                "entity_name": entity["entity_name"],
                "entity_type": entity.get("entity_type", "unknown"),
                "entity_confidence": entity.get("entity_confidence", 0.0),
                "matched_alias": entity.get("matched_alias", entity["entity_name"]),
                "subject": clean_text(item.get("subject")),
                "timestamp": item_ts.isoformat() if item_ts else "",
                "importance_score": importance_score,
                "verticals": verticals,
            }

            aggregate["mentions"].append(mention_record)

            if item_ts is not None:
                current_latest = aggregate["latest_mention_timestamp"]

                if current_latest is None or item_ts > current_latest:
                    aggregate["latest_mention_timestamp"] = item_ts
                    aggregate["latest_mention_item_id"] = mention_record["item_id"]
                    aggregate["latest_mention_source"] = source_name
                    aggregate["latest_mention_subject"] = mention_record["subject"]
                    aggregate["latest_mention_preview"] = clean_text(
                        item.get("content_preview")
                        or item.get("summary")
                        or item.get("content")
                        or item.get("raw_text")
                    )

    entities = []

    for aggregate in aggregates.values():
        mentions = sorted(
            aggregate["mentions"],
            key=lambda mention: (
                mention["timestamp"] or "",
                mention["item_id"],
            ),
        )

        mention_count = aggregate["mention_count"]
        source_names = sorted(aggregate["source_names"])
        source_types = sorted(aggregate["source_types"])
        verticals = [
            vertical
            for vertical, _count in sorted(
                aggregate["vertical_counts"].items(),
                key=lambda entry: (-entry[1], entry[0].lower()),
            )
        ]

        latest_timestamp = aggregate["latest_mention_timestamp"]
        timestamp_value = latest_timestamp.isoformat() if latest_timestamp else ""
        average_importance = round(aggregate["importance_total"] / mention_count, 2) if mention_count else 0.0
        average_confidence = round(aggregate["confidence_total"] / mention_count, 2) if mention_count else 0.0

        if aggregate["entity_type"] == "unknown" and mention_count == 1 and average_confidence < 0.85:
            continue

        trend_label, trend_score = classify_trend(mentions)

        entity_record = {
            "entity_key": aggregate["entity_key"],
            "entity_name": aggregate["entity_name"],
            "entity_type": aggregate["entity_type"],
            "entity_confidence": average_confidence,
            "mention_count": mention_count,
            "source_diversity": len(source_names),
            "source_type_diversity": len(source_types),
            "source_names": source_names,
            "source_types": source_types,
            "average_importance_score": average_importance,
            "latest_mention_timestamp": timestamp_value,
            "latest_mention_item_id": aggregate["latest_mention_item_id"],
            "latest_mention_source": aggregate["latest_mention_source"],
            "latest_mention_subject": aggregate["latest_mention_subject"],
            "latest_mention_preview": aggregate["latest_mention_preview"],
            "associated_verticals": verticals,
            "trend_label": trend_label,
            "trend_score": trend_score,
            "mentions": mentions,
            "first_seen_index": aggregate["first_seen_index"],
        }

        entities.append(entity_record)

    entities = sorted(
        entities,
        key=lambda entity: (
            entity["entity_name"].lower(),
            entity["entity_key"],
        ),
    )

    top_emerging = sorted(
        entities,
        key=lambda entity: (
            entity["trend_score"],
            entity["mention_count"],
            entity["latest_mention_timestamp"],
            entity["entity_name"].lower(),
        ),
        reverse=True,
    )

    top_most_mentioned = sorted(
        entities,
        key=lambda entity: (
            entity["mention_count"],
            entity["source_type_diversity"],
            entity["latest_mention_timestamp"],
            entity["entity_name"].lower(),
        ),
        reverse=True,
    )

    cross_source = sorted(
        [entity for entity in entities if entity["source_type_diversity"] >= 2],
        key=lambda entity: (
            entity["source_type_diversity"],
            entity["mention_count"],
            entity["trend_score"],
            entity["entity_name"].lower(),
        ),
        reverse=True,
    )

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "log_path": str(log_path),
        "entity_count": len(entities),
        "entities": entities,
        "top_emerging_entities": [entity_without_mentions(entity) for entity in top_emerging[:5]],
        "most_mentioned_entities": [entity_without_mentions(entity) for entity in top_most_mentioned[:5]],
        "cross_source_entities": [entity_without_mentions(entity) for entity in cross_source[:5]],
    }

    output_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    write_entity_files(entity_dir, entities)
    return summary


def entity_without_mentions(entity):
    return {
        "entity_key": entity["entity_key"],
        "entity_name": entity["entity_name"],
        "entity_type": entity.get("entity_type", "unknown"),
        "entity_confidence": entity.get("entity_confidence", 0.0),
        "mention_count": entity["mention_count"],
        "source_diversity": entity["source_diversity"],
        "source_type_diversity": entity["source_type_diversity"],
        "source_names": entity["source_names"],
        "source_types": entity["source_types"],
        "average_importance_score": entity["average_importance_score"],
        "latest_mention_timestamp": entity["latest_mention_timestamp"],
        "latest_mention_item_id": entity["latest_mention_item_id"],
        "latest_mention_source": entity["latest_mention_source"],
        "latest_mention_subject": entity["latest_mention_subject"],
        "latest_mention_preview": entity["latest_mention_preview"],
        "associated_verticals": entity["associated_verticals"],
        "trend_label": entity["trend_label"],
        "trend_score": entity["trend_score"],
    }


def classify_trend(mentions):
    if len(mentions) < 3:
        return "stable", 0.0

    parsed_mentions = []

    for index, mention in enumerate(mentions):
        timestamp = parse_timestamp(mention.get("timestamp"))

        if timestamp is None:
            continue

        parsed_mentions.append(
            {
                "timestamp": timestamp,
                "importance_score": safe_int(mention.get("importance_score"), 1),
                "index": index,
            }
        )

    if len(parsed_mentions) < 3:
        return "stable", 0.0

    parsed_mentions.sort(key=lambda mention: (mention["timestamp"], mention["index"]))
    first_timestamp = parsed_mentions[0]["timestamp"]
    last_timestamp = parsed_mentions[-1]["timestamp"]

    if last_timestamp <= first_timestamp:
        return "stable", 0.0

    span_seconds = max((last_timestamp - first_timestamp).total_seconds(), 0)

    if span_seconds < 24 * 60 * 60:
        return "stable", 0.0

    cutoff_index = max(1, int(len(parsed_mentions) * 0.67))
    older_mentions = parsed_mentions[:cutoff_index]
    recent_mentions = parsed_mentions[cutoff_index:]

    if not recent_mentions or not older_mentions:
        return "stable", 0.0

    recent_score = sum(mention["importance_score"] for mention in recent_mentions)
    older_score = sum(mention["importance_score"] for mention in older_mentions)
    total_score = recent_score + older_score
    trend_score = round((recent_score - older_score) / max(total_score, 1), 4)

    if len(recent_mentions) >= 2 and recent_score >= older_score * 1.25:
        return "rising", trend_score

    if len(older_mentions) >= 2 and recent_score <= older_score * 0.75:
        return "fading", trend_score

    return "stable", trend_score


def build_entity_filename(entity_key):
    normalized_key = clean_text(entity_key)
    digest = hashlib.sha256(normalized_key.lower().encode("utf-8")).hexdigest()[:16]
    safe_name = re.sub(r"[^a-z0-9]+", "-", normalized_key.lower()).strip("-")

    if not safe_name:
        safe_name = "entity"

    reserved_length = len(digest) + len(ENTITY_FILENAME_EXTENSION) + 1
    max_safe_length = max(1, MAX_ENTITY_FILENAME_LENGTH - reserved_length)
    safe_name = safe_name[:max_safe_length].strip("-") or "entity"

    return f"{safe_name}-{digest}{ENTITY_FILENAME_EXTENSION}"


def entity_file_name(entity):
    return build_entity_filename(entity["entity_key"])


def write_entity_files(entity_dir, entities):
    entity_dir = Path(entity_dir)
    entity_dir.mkdir(parents=True, exist_ok=True)

    for entity in entities:
        file_path = entity_dir / build_entity_filename(entity["entity_key"])
        payload = dict(entity)
        payload["mentions"] = entity["mentions"][:25]
        file_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def main():
    summary = build_entity_summary()
    print(f"Generated {summary['entity_count']} entities.")


if __name__ == "__main__":
    main()
