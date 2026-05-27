import argparse
import difflib
import hashlib
import json
import re
from datetime import UTC, datetime, date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_PROMOTED_DIR = REPO_ROOT / "data" / "hermes" / "promoted"
DEFAULT_WIKI_ROOT = REPO_ROOT / "workspace" / "wiki"
DEFAULT_TITLE_SIMILARITY_THRESHOLD = 0.7
DEFAULT_PARTITION_FALLBACK_DATE = "1970-01-01"
MAX_FILENAME_LENGTH = 120
TITLE_NOISE_WORDS = {
    "a",
    "an",
    "and",
    "around",
    "brief",
    "digest",
    "followup",
    "for",
    "from",
    "in",
    "memo",
    "note",
    "notes",
    "of",
    "on",
    "report",
    "summary",
    "the",
    "update",
    "weekly",
}


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


def append_jsonl(path, records):
    if not records:
        return

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def safe_text(value):
    return str(value or "").strip()


def normalize_whitespace(value):
    return re.sub(r"\s+", " ", safe_text(value)).strip()


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
        text = normalize_whitespace(entry)

        if not text or text in seen:
            continue

        seen.add(text)
        normalized.append(text)

    return normalized


def flatten_text_values(value):
    values = []

    if not value:
        return values

    if isinstance(value, dict):
        for key in ("canonical_name", "entity_name", "name", "label", "title"):
            candidate = value.get(key)
            if candidate:
                values.append(candidate)
                break
        return values

    if isinstance(value, list):
        for entry in value:
            values.extend(flatten_text_values(entry))
        return values

    values.append(value)
    return values


def normalize_source_url(url):
    text = normalize_whitespace(url)

    if not text:
        return ""

    parts = urlsplit(text)

    if not parts.scheme and not parts.netloc:
        return text

    path = parts.path or ""

    if path not in {"", "/"}:
        path = path.rstrip("/")

    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            parts.query,
            "",
        )
    )


def extract_title(record):
    for key in ("title", "subject", "summary", "source_name"):
        value = normalize_whitespace(record.get(key))
        if value:
            return value

    return safe_text(record.get("promotion_hash") or "Hermes memory")


def extract_source(record):
    source_name = normalize_whitespace(record.get("source_name"))
    source_type = normalize_whitespace(record.get("source_type"))

    if source_name and source_type:
        return f"{source_name} ({source_type})"

    if source_name:
        return source_name

    if source_type:
        return source_type

    return "Unknown"


def extract_timestamp(record):
    for key in ("timestamp", "source_timestamp", "promoted_at", "created_at"):
        value = normalize_whitespace(record.get(key))
        if value:
            return value

    return ""


def extract_verticals(record):
    return normalize_list(record.get("verticals"))


def extract_promotion_reasons(record):
    reasons = normalize_list(record.get("promotion_reasons"))

    if reasons:
        return reasons

    reason_fields = record.get("promotion_reason_fields") or {}
    signal_details = reason_fields.get("signal_details") or []
    derived = []

    for item in signal_details:
        if not isinstance(item, dict):
            continue
        signal = normalize_whitespace(item.get("signal"))
        value = item.get("value")
        if signal and value not in (None, "", []):
            derived.append(f"{signal}={normalize_whitespace(value)}")

    return normalize_list(derived)


def extract_confidence(record):
    confidence = record.get("confidence")

    if confidence in (None, ""):
        confidence = record.get("promotion_confidence")

    try:
        return int(confidence)
    except (TypeError, ValueError):
        return 0


def extract_canonical_entities(record):
    values = []

    for key in ("canonical_entities", "canonical_entity", "entities", "entity_names"):
        values.extend(flatten_text_values(record.get(key)))

    reason_fields = record.get("promotion_reason_fields") or {}
    values.extend(flatten_text_values(reason_fields.get("entity_evidence")))
    values.extend(flatten_text_values(record.get("best_entity")))

    normalized = []
    seen = set()

    for value in values:
        text = normalize_whitespace(value)

        if not text or text in seen:
            continue

        seen.add(text)
        normalized.append(text)

    return normalized


def extract_narrative_membership(record):
    values = []

    for key in (
        "narrative_membership",
        "narrative_memberships",
        "narratives",
        "related_narratives",
    ):
        values.extend(flatten_text_values(record.get(key)))

    normalized = []
    seen = set()

    for value in values:
        text = normalize_whitespace(value)

        if not text or text in seen:
            continue

        seen.add(text)
        normalized.append(text)

    return normalized


def normalize_title_for_similarity(title):
    tokens = []

    for token in re.findall(r"[A-Za-z0-9]+", normalize_whitespace(title).lower()):
        if token in TITLE_NOISE_WORDS:
            continue
        tokens.append(token)

    return " ".join(tokens).strip()


def title_similarity(left, right):
    left_text = normalize_title_for_similarity(left)
    right_text = normalize_title_for_similarity(right)

    if not left_text or not right_text:
        return 0.0

    sequence_ratio = difflib.SequenceMatcher(None, left_text, right_text).ratio()
    left_tokens = set(left_text.split())
    right_tokens = set(right_text.split())
    token_overlap = len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))

    return max(sequence_ratio, token_overlap)


def canonical_entity_signature(canonical_entities):
    if not canonical_entities:
        return ""

    normalized = []

    for entity in canonical_entities:
        text = re.sub(r"[^A-Za-z0-9]+", "-", normalize_whitespace(entity).lower()).strip("-")
        if text:
            normalized.append(text)

    return "|".join(sorted(dict.fromkeys(normalized)))


def title_signature(title):
    normalized = normalize_title_for_similarity(title)

    if normalized:
        return normalized

    return re.sub(r"\s+", " ", normalize_whitespace(title).lower()).strip()


def slugify(value, fallback="item"):
    text = normalize_whitespace(value).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")

    return text or fallback


def stable_hash_suffix(payload):
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def build_markdown_artifact(metadata):
    frontmatter_lines = [
        "---",
        f"title: {json.dumps(metadata['title'])}",
        f"source: {json.dumps(metadata['source'])}",
        f"timestamp: {json.dumps(metadata['timestamp'])}",
        "canonical_entities:",
    ]

    for entity in metadata["canonical_entities"]:
        frontmatter_lines.append(f"  - {json.dumps(entity)}")

    frontmatter_lines.append("verticals:")

    for vertical in metadata["verticals"]:
        frontmatter_lines.append(f"  - {json.dumps(vertical)}")

    frontmatter_lines.append("promotion_reasons:")

    for reason in metadata["promotion_reasons"]:
        frontmatter_lines.append(f"  - {json.dumps(reason)}")

    frontmatter_lines.extend(
        [
            f"confidence: {metadata['confidence']}",
            "narrative_membership:",
        ]
    )

    for narrative in metadata["narrative_membership"]:
        frontmatter_lines.append(f"  - {json.dumps(narrative)}")

    frontmatter_lines.extend(
        [
            f"source_url: {json.dumps(metadata['source_url'])}",
            f"promotion_hash: {json.dumps(metadata['promotion_hash'])}",
            f"memory_id: {json.dumps(metadata['memory_id'])}",
            "---",
            "",
            f"# {metadata['title']}",
            "",
            "## Source",
            f"- Source: {metadata['source']}",
            f"- Timestamp: {metadata['timestamp'] or 'Unknown'}",
        ]
    )

    if metadata["source_url"]:
        frontmatter_lines.append(f"- Source URL: {metadata['source_url']}")

    frontmatter_lines.extend(
        [
            "",
            "## Canonical Entities",
        ]
    )

    if metadata["canonical_entities"]:
        for entity in metadata["canonical_entities"]:
            frontmatter_lines.append(f"- {entity}")
    else:
        frontmatter_lines.append("- None listed")

    frontmatter_lines.extend(
        [
            "",
            "## Verticals",
        ]
    )

    if metadata["verticals"]:
        for vertical in metadata["verticals"]:
            frontmatter_lines.append(f"- {vertical}")
    else:
        frontmatter_lines.append("- None listed")

    frontmatter_lines.extend(
        [
            "",
            "## Promotion Reasons",
        ]
    )

    if metadata["promotion_reasons"]:
        for reason in metadata["promotion_reasons"]:
            frontmatter_lines.append(f"- {reason}")
    else:
        frontmatter_lines.append("- None listed")

    if metadata["narrative_membership"]:
        frontmatter_lines.extend(
            [
                "",
                "## Related Narratives",
            ]
        )

        for narrative in metadata["narrative_membership"]:
            frontmatter_lines.append(f"- {narrative}")

    frontmatter_lines.extend(
        [
            "",
            "## Confidence",
            f"- {metadata['confidence']}",
            "",
        ]
    )

    return "\n".join(frontmatter_lines)


def build_memory_metadata(record, partition_date):
    title = extract_title(record)
    canonical_entities = extract_canonical_entities(record)
    verticals = extract_verticals(record)
    promotion_reasons = extract_promotion_reasons(record)
    narrative_membership = extract_narrative_membership(record)
    confidence = extract_confidence(record)
    source = extract_source(record)
    timestamp = extract_timestamp(record)
    source_url = normalize_source_url(
        record.get("source_url") or record.get("url") or record.get("source_link")
    )
    source_promotion_hash = safe_text(
        record.get("promotion_hash") or record.get("event_id") or record.get("dedupe_hash")
    )
    canonical_entity_signature_value = canonical_entity_signature(canonical_entities)
    title_signature_value = title_signature(title)
    memory_hash = stable_hash_suffix(
        {
            "canonical_entity_signature": canonical_entity_signature_value,
            "title_signature": title_signature_value,
            "source_url": source_url,
            "source_promotion_hash": source_promotion_hash,
            "timestamp": timestamp,
        }
    )
    primary_entity = canonical_entities[0] if canonical_entities else "unclassified"
    safe_entity = slugify(primary_entity, fallback="unclassified")
    file_name = f"{safe_entity}--{memory_hash}.md"

    if len(file_name) > MAX_FILENAME_LENGTH:
        file_name = f"{safe_entity[: MAX_FILENAME_LENGTH - len(memory_hash) - 6]}--{memory_hash}.md"

    memory_id = f"{safe_entity}--{memory_hash}"
    file_path = Path("aeon") / partition_date / file_name

    markdown = build_markdown_artifact(
        {
            "title": title,
            "source": source,
            "timestamp": timestamp,
            "canonical_entities": canonical_entities,
            "verticals": verticals,
            "promotion_reasons": promotion_reasons,
            "confidence": confidence,
            "narrative_membership": narrative_membership,
            "source_url": source_url,
            "promotion_hash": source_promotion_hash,
            "memory_id": memory_id,
        }
    )

    content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()[:16]

    index_record = {
        "schema_version": 1,
        "memory_id": memory_id,
        "title": title,
        "title_signature": title_signature_value,
        "source": source,
        "source_type": safe_text(record.get("source_type")),
        "timestamp": timestamp,
        "source_url": source_url,
        "canonical_entities": canonical_entities,
        "canonical_entity_signature": canonical_entity_signature_value,
        "verticals": verticals,
        "promotion_reasons": promotion_reasons,
        "confidence": confidence,
        "narrative_membership": narrative_membership,
        "promotion_hash": source_promotion_hash,
        "source_promotion_hash": source_promotion_hash,
        "partition_date": partition_date,
        "file_path": str(file_path),
        "content_hash": content_hash,
        "indexed_at": timestamp or f"{partition_date}T00:00:00+00:00",
    }

    return {
        "memory_id": memory_id,
        "file_path": file_path,
        "index_record": index_record,
        "markdown": markdown,
        "source_url": source_url,
        "title": title,
        "title_signature": title_signature_value,
        "canonical_entity_signature": canonical_entity_signature_value,
        "promotion_hash": source_promotion_hash,
    }


def load_existing_index(index_path):
    records = load_jsonl(index_path)
    normalized = {
        "promotion_hashes": set(),
        "source_urls": set(),
        "entity_titles": [],
        "memory_ids": set(),
        "file_paths": set(),
    }

    for record in records:
        promotion_hash = safe_text(record.get("promotion_hash") or record.get("source_promotion_hash"))
        source_url = normalize_source_url(record.get("source_url"))
        entity_signature = safe_text(record.get("canonical_entity_signature"))
        title = safe_text(record.get("title"))
        title_signature_value = safe_text(record.get("title_signature")) or title_signature(title)
        memory_id = safe_text(record.get("memory_id"))
        file_path = safe_text(record.get("file_path"))

        if promotion_hash:
            normalized["promotion_hashes"].add(promotion_hash)
        if source_url:
            normalized["source_urls"].add(source_url)
        if entity_signature and title_signature_value:
            normalized["entity_titles"].append(
                {
                    "entity_signature": entity_signature,
                    "title_signature": title_signature_value,
                    "title": title,
                }
            )
        if memory_id:
            normalized["memory_ids"].add(memory_id)
        if file_path:
            normalized["file_paths"].add(file_path)

    return records, normalized


def should_dedupe(metadata, existing_index):
    if metadata["memory_id"] in existing_index["memory_ids"]:
        return True, "memory_id"

    if metadata["source_url"] and metadata["source_url"] in existing_index["source_urls"]:
        return True, "source_url"

    if metadata["promotion_hash"] in existing_index["promotion_hashes"]:
        return True, "promotion_hash"

    for entry in existing_index["entity_titles"]:
        if entry["entity_signature"] != metadata["canonical_entity_signature"]:
            continue

        if not entry["title_signature"] or not metadata["title_signature"]:
            continue

        if entry["title_signature"] == metadata["title_signature"]:
            return True, "entity_title_signature"

        if title_similarity(entry["title"], metadata["title"]) >= DEFAULT_TITLE_SIMILARITY_THRESHOLD:
            return True, "entity_title_similarity"

    return False, ""


def read_promoted_records(promoted_path):
    return load_jsonl(promoted_path)


def ingest_promotions(
    promoted_path=DEFAULT_PROMOTED_DIR / f"{date.today().isoformat()}.jsonl",
    wiki_root=DEFAULT_WIKI_ROOT,
    index_path=None,
    partition_date="",
    dry_run=False,
):
    promoted_path = Path(promoted_path)
    wiki_root = Path(wiki_root)
    index_path = Path(index_path) if index_path is not None else wiki_root / "meta" / "aeon_index.jsonl"

    if not partition_date:
        partition_date = promoted_path.stem if promoted_path.stem else DEFAULT_PARTITION_FALLBACK_DATE

    records = read_promoted_records(promoted_path)

    if not records:
        return {
            "input_count": 0,
            "selected_count": 0,
            "wiki_writes": 0,
            "index_writes": 0,
            "index_path": index_path,
            "promoted_path": promoted_path,
            "written_artifacts": [],
            "suppressed_count": 0,
        }

    existing_index_records, existing_index = load_existing_index(index_path)
    _ = existing_index_records

    written_artifacts = []
    wiki_writes = []
    index_writes = []
    suppressed_count = 0

    for record in records:
        metadata = build_memory_metadata(record, partition_date)
        duplicate, _reason = should_dedupe(metadata, existing_index)

        if duplicate:
            suppressed_count += 1
            continue

        wiki_writes.append(
            {
                "file_path": metadata["file_path"],
                "markdown": metadata["markdown"],
            }
        )
        index_writes.append(metadata["index_record"])
        written_artifacts.append(metadata)

        existing_index["memory_ids"].add(metadata["memory_id"])
        if metadata["source_url"]:
            existing_index["source_urls"].add(metadata["source_url"])
        if metadata["promotion_hash"]:
            existing_index["promotion_hashes"].add(metadata["promotion_hash"])
        existing_index["entity_titles"].append(
            {
                "entity_signature": metadata["canonical_entity_signature"],
                "title_signature": metadata["title_signature"],
                "title": metadata["title"],
            }
        )

    if not dry_run:
        for entry in wiki_writes:
            file_path = wiki_root / entry["file_path"]
            file_path.parent.mkdir(parents=True, exist_ok=True)

            if file_path.exists():
                existing_text = file_path.read_text(encoding="utf-8")
                if existing_text == entry["markdown"]:
                    continue

            file_path.write_text(entry["markdown"], encoding="utf-8")

        append_jsonl(index_path, index_writes)

    return {
        "input_count": len(records),
        "selected_count": len(written_artifacts),
        "wiki_writes": len(wiki_writes),
        "index_writes": len(index_writes),
        "index_path": index_path,
        "promoted_path": promoted_path,
        "written_artifacts": written_artifacts,
        "suppressed_count": suppressed_count,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Materialize Hermes promotions into append-safe wiki memory artifacts."
    )
    parser.add_argument(
        "--promoted-path",
        default="",
        help="Promoted Hermes JSONL file to ingest. Defaults to data/hermes/promoted/YYYY-MM-DD.jsonl.",
    )
    parser.add_argument(
        "--promoted-dir",
        default=str(DEFAULT_PROMOTED_DIR),
        help="Directory that contains promoted Hermes JSONL partitions.",
    )
    parser.add_argument(
        "--wiki-root",
        default=str(DEFAULT_WIKI_ROOT),
        help="Root directory for Hermes wiki artifacts.",
    )
    parser.add_argument(
        "--index-path",
        default="",
        help="Append-only index JSONL path.",
    )
    parser.add_argument(
        "--date",
        default="",
        help="Partition date to read and write. Defaults to today's date if no promoted path is supplied.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate ingestion without writing files.",
    )

    args = parser.parse_args()

    if args.promoted_path:
        promoted_path = Path(args.promoted_path)
        partition_date = args.date or promoted_path.stem
    else:
        partition_date = args.date or date.today().isoformat()
        promoted_path = Path(args.promoted_dir) / f"{partition_date}.jsonl"

    result = ingest_promotions(
        promoted_path=promoted_path,
        wiki_root=Path(args.wiki_root),
        index_path=Path(args.index_path) if args.index_path else None,
        partition_date=partition_date,
        dry_run=args.dry_run,
    )

    if result["input_count"] == 0:
        print("No promoted Hermes records found.")
        raise SystemExit(0)

    if args.dry_run:
        print(
            "Dry run: {} wiki artifacts selected; {} wiki writes; {} index writes.".format(
                result["selected_count"],
                result["wiki_writes"],
                result["index_writes"],
            )
        )
    else:
        print(
            "Ingested {} Hermes promotions into {} wiki artifacts and {} index rows.".format(
                result["selected_count"],
                result["wiki_writes"],
                result["index_writes"],
            )
        )
        print(f"Promoted: {result['promoted_path']}")
        print(f"Index: {result['index_path']}")


if __name__ == "__main__":
    main()
