import argparse
import json
import re
from datetime import datetime, UTC
from pathlib import Path


DEFAULT_DIGEST_PATH = Path("data/processed/daily_digest.md")
DEFAULT_ALERTS_PATH = Path("data/processed/alert_candidates.jsonl")
DEFAULT_HERMES_DIR = Path("data/hermes/promoted")
DEFAULT_OUTBOX_DIR = Path("data/outbox/slack/daily-intel-digest")

HEADER_PREFIX = "# "
SECTION_PREFIX = "## "
GENERATED_PREFIX = "Generated:"
ENTITY_SECTION_TITLES = {
    "Top Emerging Entities",
    "Most-mentioned Entities",
    "Cross-source Entities",
}


def clean_text(value):
    text = str(value or "")
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def truncate_text(value, limit):
    text = clean_text(value)

    if len(text) <= limit:
        return text

    if limit <= 1:
        return text[:limit]

    return text[: limit - 1].rstrip() + "…"


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


def count_jsonl_records(path):
    return len(load_jsonl_records(path))


def parse_digest_bullet(line):
    if not line.startswith("- `"):
        return None

    parts = line[2:].split(" — ", 5)

    if len(parts) != 6:
        return None

    item_id = parts[0].strip("`")
    source = parts[1].strip().strip("*")
    subject = parts[2].strip()
    signal = parts[3].strip().strip("*")
    tags = parts[4].removeprefix("tags:").strip()
    preview = parts[5].strip()

    return {
        "item_id": clean_text(item_id),
        "source": clean_text(source),
        "subject": clean_text(subject),
        "signal": clean_text(signal),
        "tags": clean_text(tags),
        "preview": clean_text(preview),
    }


def parse_entity_bullet(line):
    if not line.startswith("- **"):
        return None

    parts = line[2:].split(" — ")

    if len(parts) < 6:
        return None

    entity = parts[0].strip("*")
    trend = parts[1].removeprefix("trend:").strip()
    mentions = parts[2].removeprefix("mentions:").strip()
    sources = parts[3].removeprefix("sources:").strip()
    avg_importance = parts[4].removeprefix("avg importance:").strip()
    latest = parts[5].removeprefix("latest:").strip()
    verticals = parts[6].removeprefix("verticals:").strip() if len(parts) > 6 else ""

    return {
        "entity": clean_text(entity),
        "trend": clean_text(trend),
        "mentions": clean_text(mentions),
        "sources": clean_text(sources),
        "avg_importance": clean_text(avg_importance),
        "latest": clean_text(latest),
        "verticals": clean_text(verticals),
    }


def parse_digest(digest_path):
    digest_path = Path(digest_path)

    if not digest_path.exists():
        return {
            "title": "Daily Intelligence Digest",
            "generated_at": "",
            "vertical_groups": [],
            "entity_sections": [],
        }

    title = "Daily Intelligence Digest"
    generated_at = ""
    vertical_groups = []
    entity_sections = []
    current_group = None
    current_section_type = ""

    for raw_line in digest_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith(HEADER_PREFIX) and title == "Daily Intelligence Digest":
            title = line.removeprefix(HEADER_PREFIX).strip()
            continue

        if line.startswith(GENERATED_PREFIX):
            generated_at = line.removeprefix(GENERATED_PREFIX).strip()
            continue

        if line.startswith(SECTION_PREFIX):
            section_title = line.removeprefix(SECTION_PREFIX).strip()

            if section_title.lower() == "topic clusters":
                current_group = None
                current_section_type = ""
                continue

            if section_title in ENTITY_SECTION_TITLES:
                current_group = {"section": section_title, "items": []}
                entity_sections.append(current_group)
                current_section_type = "entity"
                continue

            current_group = {"vertical": section_title, "items": []}
            vertical_groups.append(current_group)
            current_section_type = "vertical"
            continue

        if current_group and current_section_type == "vertical" and line.startswith("- "):
            parsed = parse_digest_bullet(line)

            if parsed:
                current_group["items"].append(parsed)

        if current_group and current_section_type == "entity" and line.startswith("- **"):
            parsed = parse_entity_bullet(line)

            if parsed:
                current_group["items"].append(parsed)

    return {
        "title": title,
        "generated_at": generated_at,
        "vertical_groups": vertical_groups,
        "entity_sections": entity_sections,
    }


def parse_digest_date(generated_at, fallback_date=None):
    if fallback_date:
        return fallback_date

    if not generated_at:
        return datetime.now(UTC).date().isoformat()

    normalized = generated_at.replace("Z", "+00:00")

    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        return datetime.now(UTC).date().isoformat()


def summarize_vertical_group(group):
    items = group.get("items", [])
    item_count = len(items)

    if not items:
        return {
            "vertical": clean_text(group.get("vertical")),
            "item_count": 0,
            "summary": "No digest items available.",
        }

    top_item = items[0]
    summary_bits = []

    if top_item.get("source"):
        summary_bits.append(top_item["source"])

    if top_item.get("subject"):
        summary_bits.append(top_item["subject"])

    summary = " / ".join(summary_bits) if summary_bits else "Digest item"

    if item_count > 1:
        summary = f"{summary}; +{item_count - 1} more"

    return {
        "vertical": clean_text(group.get("vertical")),
        "item_count": item_count,
        "summary": truncate_text(summary, 180),
    }


def build_text_payload(payload):
    parts = [
        f"{payload['title']} ({payload['date']})",
        f"{payload['top_alerts_count']} alert(s)",
        f"{payload['promoted_to_hermes_count']} Hermes promotions",
    ]

    vertical_parts = []

    for group in payload.get("grouped_vertical_summaries", [])[:4]:
        vertical_parts.append(f"{group['vertical']}: {group['summary']}")

    if vertical_parts:
        parts.append(" | ".join(vertical_parts))

    entity_parts = []

    for group in payload.get("entity_section_summaries", [])[:3]:
        entity_parts.append(f"{group['section']}: {group['summary']}")

    if entity_parts:
        parts.append(" | ".join(entity_parts))

    return truncate_text(" | ".join(parts), 2800)


def summarize_entity_group(group):
    items = group.get("items", [])
    item_count = len(items)

    if not items:
        return {
            "section": clean_text(group.get("section")),
            "item_count": 0,
            "summary": "No entity signals available.",
        }

    top_item = items[0]
    summary = (
        f"{top_item.get('entity', 'Unknown')} "
        f"({top_item.get('trend', 'stable')}, "
        f"{top_item.get('mentions', 0)} mentions, "
        f"{top_item.get('sources', 0)} sources)"
    )

    if item_count > 1:
        summary = f"{summary}; +{item_count - 1} more"

    return {
        "section": clean_text(group.get("section")),
        "item_count": item_count,
        "summary": truncate_text(summary, 180),
    }


def build_slack_digest_payload(
    digest_path=DEFAULT_DIGEST_PATH,
    alerts_path=DEFAULT_ALERTS_PATH,
    hermes_dir=DEFAULT_HERMES_DIR,
    outbox_dir=DEFAULT_OUTBOX_DIR,
    run_date="",
):
    digest_path = Path(digest_path)
    alerts_path = Path(alerts_path)
    hermes_dir = Path(hermes_dir)
    outbox_dir = Path(outbox_dir)

    digest = parse_digest(digest_path)
    digest_date = parse_digest_date(digest["generated_at"], run_date or "")
    hermes_path = hermes_dir / f"{digest_date}.jsonl"

    grouped_vertical_summaries = [
        summarize_vertical_group(group)
        for group in digest["vertical_groups"]
    ]
    entity_section_summaries = [
        summarize_entity_group(group)
        for group in digest["entity_sections"]
    ]

    payload = {
        "title": clean_text(digest["title"]),
        "date": digest_date,
        "top_alerts_count": count_jsonl_records(alerts_path),
        "promoted_to_hermes_count": count_jsonl_records(hermes_path),
        "grouped_vertical_summaries": grouped_vertical_summaries,
        "entity_section_summaries": entity_section_summaries,
        "full_digest_path": str(digest_path) if digest_path.exists() else None,
    }
    payload["text"] = build_text_payload(payload)

    output_path = outbox_dir / f"{digest_date}.json"

    return {
        "payload": payload,
        "output_path": output_path,
    }


def write_payload(output_path, payload):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build a Slack-safe AEON digest payload from local artifacts."
    )
    parser.add_argument(
        "--digest-path",
        default=str(DEFAULT_DIGEST_PATH),
        help="Path to the generated Markdown digest artifact.",
    )
    parser.add_argument(
        "--alerts-path",
        default=str(DEFAULT_ALERTS_PATH),
        help="Path to the generated alert-candidates JSONL artifact.",
    )
    parser.add_argument(
        "--hermes-dir",
        default=str(DEFAULT_HERMES_DIR),
        help="Directory that contains Hermes promotion JSONL artifacts.",
    )
    parser.add_argument(
        "--outbox-dir",
        default=str(DEFAULT_OUTBOX_DIR),
        help="Directory where Slack-safe outbox payloads are written.",
    )
    parser.add_argument(
        "--date",
        default="",
        help="Override the payload partition date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--preview",
        "--dry-run",
        action="store_true",
        dest="preview",
        help="Print the payload without writing the outbox artifact.",
    )

    args = parser.parse_args(argv)

    result = build_slack_digest_payload(
        digest_path=Path(args.digest_path),
        alerts_path=Path(args.alerts_path),
        hermes_dir=Path(args.hermes_dir),
        outbox_dir=Path(args.outbox_dir),
        run_date=args.date,
    )

    payload = result["payload"]
    output_path = result["output_path"]

    if args.preview:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    write_payload(output_path, payload)
    print(f"Wrote Slack payload to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
