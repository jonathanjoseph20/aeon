import argparse
import hashlib
import json
import sys
from datetime import datetime, UTC
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import yaml


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


def collect_inputs(inputs):
    files = []

    for raw_input in inputs:
        path = Path(raw_input)

        if path.is_dir():
            files.extend(sorted(path.glob("*.jsonl")))
        elif path.suffix.lower() == ".jsonl":
            files.append(path)

    return files


def load_twitter_sources():
    config = load_yaml(Path("config/sources.yml"))
    registry = {}

    for entry in config.get("twitter", []) or []:
        handle = normalize_handle(entry.get("handle"))

        if not handle:
            continue

        registry[handle] = {
            "name": entry.get("name") or entry.get("handle") or "Unknown",
            "priority": entry.get("priority", "low"),
            "importance_score": safe_int(entry.get("importance_score", 1)),
            "verticals": entry.get("verticals", []) or []
        }

    return registry


def get_first(record, keys):
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return ""


def extract_handle(record):
    if isinstance(record.get("user"), dict):
        nested = record["user"]
        handle = get_first(
            nested,
            ["screen_name", "username", "handle", "name"]
        )

        if handle:
            return handle

    return get_first(
        record,
        [
            "author_handle",
            "handle",
            "username",
            "screen_name",
            "user_handle",
            "author"
        ]
    )


def extract_text(record):
    return get_first(
        record,
        ["text", "full_text", "content", "body", "tweet_text", "message"]
    )


def build_record(raw_record, source_file, twitter_sources):
    text = str(extract_text(raw_record) or "").strip()

    if not text:
        return None

    handle = normalize_handle(extract_handle(raw_record))
    source_meta = twitter_sources.get(handle, {})
    tweet_id = str(
        get_first(
            raw_record,
            ["id", "tweet_id", "status_id", "tweetId", "id_str"]
        )
    ).strip()

    source_name = (
        raw_record.get("source_name")
        or source_meta.get("name")
        or handle
        or Path(source_file).stem
        or "twitter"
    )
    priority = raw_record.get("priority") or source_meta.get("priority", "low")
    importance_score = safe_int(
        raw_record.get("importance_score"),
        source_meta.get("importance_score", 1)
    )
    verticals = raw_record.get("verticals") or source_meta.get("verticals", [])
    subject = raw_record.get("subject") or text[:120]
    source_url = get_first(raw_record, ["url", "tweet_url", "source_url"])

    if not source_url and handle and tweet_id:
        source_url = f"https://x.com/{handle}/status/{tweet_id}"

    normalized_content = text.lower().strip()
    dedupe_hash = hashlib.sha256(
        normalized_content.encode("utf-8")
    ).hexdigest()[:16]

    return {
        "source_type": "twitter",
        "source_file": str(Path(source_file).resolve()),
        "source_id": tweet_id or source_url or handle or source_file,
        "source_name": source_name,
        "source_handle": handle,
        "source_url": source_url,
        "source_domain": "x.com" if handle else "",
        "known_source": "True" if handle in twitter_sources else "False",
        "subject": subject,
        "priority": priority,
        "importance_score": importance_score,
        "verticals": verticals,
        "content": text,
        "content_preview": text[:400],
        "created_at": get_first(raw_record, ["created_at", "posted_at", "timestamp"]),
        "dedupe_hash": dedupe_hash,
        "item_id": dedupe_hash,
        "timestamp": datetime.now(UTC).isoformat(),
        "raw_text": text
    }


def main():
    parser = argparse.ArgumentParser(
        description="Normalize manual Twitter JSONL exports into AEON intake records."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="One or more JSONL files or directories containing JSONL files."
    )
    parser.add_argument(
        "--output-dir",
        default="data/intake/twitter",
        help="Directory where normalized JSONL files will be written."
    )
    parser.add_argument(
        "--source-name",
        default="",
        help="Optional source name override for records without a configured handle."
    )
    parser.add_argument(
        "--priority",
        default="low",
        choices=["low", "medium", "high"],
        help="Fallback priority when the source is not configured."
    )
    parser.add_argument(
        "--importance-score",
        default=1,
        help="Fallback importance score when the source is not configured."
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    twitter_sources = load_twitter_sources()
    input_files = collect_inputs(args.inputs)

    if not input_files:
        print("No Twitter JSONL files found.")
        raise SystemExit(0)

    for input_file in input_files:
        records = []

        for line in Path(input_file).read_text().splitlines():
            if not line.strip():
                continue

            raw_record = json.loads(line)

            if not isinstance(raw_record, dict):
                continue

            record = build_record(raw_record, input_file, twitter_sources)

            if not record:
                continue

            if args.source_name and not record["source_handle"]:
                record["source_name"] = args.source_name

            if record["priority"] == "low" and args.priority:
                record["priority"] = args.priority

            if record["importance_score"] == 1 and args.importance_score:
                record["importance_score"] = safe_int(args.importance_score, 1)

            records.append(record)

        if not records:
            print(f"Skipped empty JSONL: {input_file}")
            continue

        output_name = (
            f"{Path(input_file).stem}-"
            f"{hashlib.sha256(str(Path(input_file).resolve()).encode('utf-8')).hexdigest()[:10]}.jsonl"
        )
        output_path = output_dir / output_name

        with output_path.open("w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
