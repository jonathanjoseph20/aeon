import argparse
import hashlib
import json
from datetime import datetime, UTC
from pathlib import Path


DEFAULT_INPUT_LOG = Path("data/processed/intake_log.jsonl")
DEFAULT_EVENT_DIR = Path("data/events/promote_to_hermes")
DEFAULT_HERMES_DIR = Path("data/hermes/promoted")
DEFAULT_IMPORTANCE_THRESHOLD = 7


def safe_int(value, default=0):
    try:
        return int(value)
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


def get_reasons(item, threshold):
    reasons = []
    score = get_importance_score(item)
    signal_band = build_signal_band(item)

    if score > threshold:
        reasons.append(f"importance_score>{threshold}")

    if item.get("watchlist_hits"):
        reasons.append("watchlist_hit")

    if signal_band == "High Signal":
        reasons.append("signal_band=High Signal")

    return reasons


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


def build_notification_payload(source_name, signal_band, importance_score, summary):
    text = "AEON promoted {} ({}, score {}): {}".format(
        source_name or "Unknown source",
        signal_band,
        importance_score,
        summary or "No summary available",
    )

    return {
        "text": text[:2800]
    }


def build_event_record(
    item,
    run_date,
    input_log_path,
    importance_threshold,
    include_slack_payloads,
):
    promotion_hash = get_promotion_hash(item)
    dedupe_hash = get_dedupe_hash(item)
    importance_score = get_importance_score(item)
    signal_band = build_signal_band(item)
    verticals = normalize_list(item.get("verticals"))
    tags = unique_tags(item)
    summary, preview = build_summary_and_preview(item)
    reasons = get_reasons(item, importance_threshold)

    event_record = {
        "schema_version": 1,
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
        "dedupe_hash": dedupe_hash,
        "signal_band": signal_band,
        "watchlist_hits": item.get("watchlist_hits", []),
        "summary": summary,
        "preview": preview,
        "promotion_reasons": reasons,
        "target_system": "hermes",
    }

    if include_slack_payloads:
        event_record["slack_notification"] = build_notification_payload(
            event_record["source_name"],
            signal_band,
            importance_score,
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
        "dedupe_hash": dedupe_hash,
        "signal_band": signal_band,
        "watchlist_hits": item.get("watchlist_hits", []),
        "summary": summary,
        "preview": preview,
        "promotion_reasons": reasons,
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
    dry_run=False,
    include_slack_payloads=False,
):
    input_log_path = Path(input_log_path)
    event_dir = Path(event_dir)
    hermes_dir = Path(hermes_dir)
    run_date = run_date or datetime.now(UTC).date().isoformat()

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
        }

    existing_event_hashes = load_existing_hashes(event_dir)
    existing_hermes_hashes = load_existing_hashes(hermes_dir)

    planned = []
    event_records = []
    hermes_records = []

    for item in items:
        reasons = get_reasons(item, importance_threshold)

        if not reasons:
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
        )

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
        help="Promote when importance_score is greater than this threshold.",
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
