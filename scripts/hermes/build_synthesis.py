import argparse
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WIKI_ROOT = REPO_ROOT / "workspace" / "wiki"
DEFAULT_INDEX_PATH = DEFAULT_WIKI_ROOT / "meta" / "aeon_index.jsonl"
DEFAULT_NARRATIVE_SUMMARY_PATH = REPO_ROOT / "data" / "processed" / "narrative_summary.json"
DEFAULT_FALLBACK_DATE = "1970-01-01"


def load_json(path):
    path = Path(path)

    if not path.exists():
        return None

    return json.loads(path.read_text(encoding="utf-8"))


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


def normalize_text(value):
    text = str(value or "")
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


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


def unique_text_list(values):
    result = []
    seen = set()

    for value in values or []:
        text = normalize_text(value)

        if not text or text in seen:
            continue

        seen.add(text)
        result.append(text)

    return result


def parse_iso_date(value):
    text = normalize_text(value)

    if not text:
        return None

    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_iso_datetime(value):
    text = normalize_text(value)

    if not text:
        return None

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed_date = parse_iso_date(text)

        if parsed_date is None:
            return None

        return datetime.combine(parsed_date, datetime.min.time())


def iso_week_key(value):
    parsed = value if isinstance(value, date) else parse_iso_date(value)

    if parsed is None:
        return ""

    iso_year, iso_week, _iso_weekday = parsed.isocalendar()
    return f"{iso_year:04d}-{iso_week:02d}"


def week_window(value):
    parsed = value if isinstance(value, date) else parse_iso_date(value)

    if parsed is None:
        parsed = parse_iso_date(DEFAULT_FALLBACK_DATE)

    iso_year, iso_week, _iso_weekday = parsed.isocalendar()
    week_start = date.fromisocalendar(iso_year, iso_week, 1)
    week_end = week_start + timedelta(days=6)
    return week_start.isoformat(), week_end.isoformat()


def load_frontmatter_markdown(path):
    path = Path(path)

    if not path.exists():
        return {
            "frontmatter": {},
            "body": "",
            "title": "",
            "sections": {},
        }

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    if not lines or lines[0].strip() != "---":
        body = text.strip()
        title = ""

        for raw_line in lines:
            line = raw_line.strip()
            if line.startswith("# "):
                title = line[2:].strip()
                break

        return {
            "frontmatter": {},
            "body": body,
            "title": title,
            "sections": parse_markdown_sections(body),
        }

    end_index = None

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break

    if end_index is None:
        body = text.strip()
        return {
            "frontmatter": {},
            "body": body,
            "title": "",
            "sections": parse_markdown_sections(body),
        }

    frontmatter_text = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :]).strip()

    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except Exception:
        frontmatter = {}

    title = normalize_text(frontmatter.get("title"))

    if not title:
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if line.startswith("# "):
                title = line[2:].strip()
                break

    return {
        "frontmatter": frontmatter if isinstance(frontmatter, dict) else {},
        "body": body,
        "title": title,
        "sections": parse_markdown_sections(body),
    }


def parse_markdown_sections(body):
    sections = {}
    current_section = ""
    current_lines = []

    for raw_line in body.splitlines():
        line = raw_line.rstrip()

        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = line[3:].strip()
            current_lines = []
            continue

        if current_section:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


def load_index_records(index_path):
    records = load_jsonl(index_path)
    deduped = {}

    for record in records:
        key = normalize_text(record.get("memory_id") or record.get("file_path") or record.get("title"))

        if not key:
            continue

        deduped[key] = record

    return list(deduped.values())


def load_wiki_records(wiki_root, index_records):
    wiki_root = Path(wiki_root)
    parsed_by_relative_path = {}
    parsed_by_memory_id = {}

    for path in sorted(wiki_root.glob("aeon/*/*.md")):
        parsed = load_frontmatter_markdown(path)
        relative_path = path.relative_to(wiki_root)
        parsed_by_relative_path[str(relative_path)] = parsed

        memory_id = normalize_text(parsed["frontmatter"].get("memory_id"))

        if memory_id:
            parsed_by_memory_id[memory_id] = parsed

    wiki_records = []

    for record in index_records:
        file_path = normalize_text(record.get("file_path"))
        memory_id = normalize_text(record.get("memory_id"))
        parsed = parsed_by_relative_path.get(file_path) or parsed_by_memory_id.get(memory_id)

        if parsed is None and file_path:
            parsed = load_frontmatter_markdown(wiki_root / file_path)

        merged = dict(record)

        if parsed:
            frontmatter = parsed.get("frontmatter") or {}
            for key, value in frontmatter.items():
                merged.setdefault(key, value)
            merged["markdown_title"] = parsed.get("title", "")
            merged["markdown_body"] = parsed.get("body", "")
            merged["markdown_sections"] = parsed.get("sections", {})
        else:
            merged["markdown_title"] = ""
            merged["markdown_body"] = ""
            merged["markdown_sections"] = {}

        wiki_records.append(merged)

    return wiki_records


def load_narrative_summary_map(narrative_summary_path):
    summary = load_json(narrative_summary_path) or {}

    narrative_priority_map = {}
    for narrative in summary.get("narratives", []) or []:
        name = normalize_text(narrative.get("narrative_name"))

        if not name:
            continue

        narrative_priority_map[name] = safe_float(narrative.get("priority_score"), 0.0)

    for narrative in summary.get("top_narratives", []) or []:
        name = normalize_text(narrative.get("narrative_name"))

        if not name:
            continue

        narrative_priority_map[name] = max(
            narrative_priority_map.get(name, 0.0),
            safe_float(narrative.get("priority_score"), 0.0),
        )

    entity_priority_map = {}
    for entity in summary.get("entities", []) or []:
        name = normalize_text(entity.get("canonical_name") or entity.get("entity_name"))

        if not name:
            continue

        entity_priority_map[name] = safe_float(entity.get("priority_score"), 0.0)

    return summary, narrative_priority_map, entity_priority_map


def resolve_target_date(index_records, target_date=""):
    if target_date:
        parsed = parse_iso_date(target_date)

        if parsed is not None:
            return parsed

    candidate_dates = []

    for record in index_records:
        partition_date = parse_iso_date(record.get("partition_date"))

        if partition_date is not None:
            candidate_dates.append(partition_date)
            continue

        timestamp = parse_iso_datetime(record.get("timestamp"))

        if timestamp is not None:
            candidate_dates.append(timestamp.date())

    if candidate_dates:
        return max(candidate_dates)

    return parse_iso_date(DEFAULT_FALLBACK_DATE)


def record_partition_date(record):
    partition_date = parse_iso_date(record.get("partition_date"))

    if partition_date is not None:
        return partition_date

    timestamp = parse_iso_datetime(record.get("timestamp"))

    if timestamp is not None:
        return timestamp.date()

    return parse_iso_date(DEFAULT_FALLBACK_DATE)


def record_scope_key(record, scope):
    partition_date = record_partition_date(record)

    if scope == "weekly":
        return iso_week_key(partition_date)

    return partition_date.isoformat()


def scope_matches(record, target_date, scope):
    partition_date = record_partition_date(record)

    if partition_date is None:
        return False

    if scope == "weekly":
        return iso_week_key(partition_date) == iso_week_key(target_date)

    return partition_date == target_date


def group_records(records, scope, target_date, narrative_priority_map, entity_priority_map):
    narrative_groups = {}
    entity_groups = {}

    for record in records:
        confidence = safe_int(record.get("confidence"), 0)
        narratives = unique_text_list(record.get("narrative_membership") or ["Unclassified"])
        entities = unique_text_list(record.get("canonical_entities") or [])
        source_name = normalize_text(record.get("source") or record.get("source_name") or "Unknown")
        partition_date = record_partition_date(record)
        in_scope = scope_matches(record, target_date, scope)

        for narrative_name in narratives:
            group = narrative_groups.setdefault(
                narrative_name,
                {
                    "narrative_name": narrative_name,
                    "records": [],
                    "scope_records": [],
                    "source_names": set(),
                    "entities": set(),
                    "first_seen_date": None,
                    "last_seen_date": None,
                    "all_time_count": 0,
                    "scope_count": 0,
                    "scope_source_count": 0,
                    "scope_promotion_confidence": 0,
                    "narrative_priority": narrative_priority_map.get(narrative_name, 0.0),
                },
            )
            group["records"].append(record)
            if in_scope:
                group["scope_records"].append(record)
                group["scope_count"] += 1
                group["source_names"].add(source_name)

            for entity_name in entities:
                group["entities"].add(entity_name)

            if group["first_seen_date"] is None or partition_date < group["first_seen_date"]:
                group["first_seen_date"] = partition_date

            if group["last_seen_date"] is None or partition_date > group["last_seen_date"]:
                group["last_seen_date"] = partition_date

            if confidence > group["scope_promotion_confidence"]:
                group["scope_promotion_confidence"] = confidence

            group["all_time_count"] += 1

        for entity_name in entities:
            group = entity_groups.setdefault(
                entity_name,
                {
                    "entity_name": entity_name,
                    "records": [],
                    "scope_records": [],
                    "source_names": set(),
                    "narratives": set(),
                    "first_seen_date": None,
                    "last_seen_date": None,
                    "scope_count": 0,
                    "scope_source_count": 0,
                    "scope_promotion_confidence": 0,
                    "entity_priority": entity_priority_map.get(entity_name, 0.0),
                },
            )
            group["records"].append(record)
            if in_scope:
                group["scope_records"].append(record)
                group["scope_count"] += 1
                group["source_names"].add(source_name)

            for narrative_name in narratives:
                group["narratives"].add(narrative_name)

            if group["first_seen_date"] is None or partition_date < group["first_seen_date"]:
                group["first_seen_date"] = partition_date

            if group["last_seen_date"] is None or partition_date > group["last_seen_date"]:
                group["last_seen_date"] = partition_date

            if confidence > group["scope_promotion_confidence"]:
                group["scope_promotion_confidence"] = confidence

    for group in narrative_groups.values():
        scope_source_names = set()
        scope_entities = set()
        scope_confidence = 0
        scope_records = group.get("scope_records", [])

        for record in scope_records:
            source_name = normalize_text(record.get("source") or record.get("source_name") or "Unknown")
            scope_source_names.add(source_name)
            scope_confidence = max(scope_confidence, safe_int(record.get("confidence"), 0))
            for entity_name in unique_text_list(record.get("canonical_entities") or []):
                scope_entities.add(entity_name)

        group["scope_source_count"] = len(scope_source_names)
        group["scope_promotion_confidence"] = scope_confidence
        group["scope_entities"] = scope_entities
        group["entity_priority"] = sum(
            entity_priority_map.get(entity_name, 0.0) for entity_name in sorted(scope_entities)
        )
        group["entity_names"] = sorted(scope_entities, key=str.lower)
        group["mention_count"] = len(scope_records)
        group["source_count"] = len(scope_source_names)
        group["first_seen_key"] = record_scope_key(
            {"partition_date": group["first_seen_date"].isoformat() if group["first_seen_date"] else ""},
            scope,
        )
        group["last_seen_key"] = record_scope_key(
            {"partition_date": group["last_seen_date"].isoformat() if group["last_seen_date"] else ""},
            scope,
        )
        group["promotion_confidence"] = scope_confidence

    for group in entity_groups.values():
        scope_source_names = set()
        scope_narratives = set()
        scope_confidence = 0
        scope_records = group.get("scope_records", [])

        for record in scope_records:
            source_name = normalize_text(record.get("source") or record.get("source_name") or "Unknown")
            scope_source_names.add(source_name)
            scope_confidence = max(scope_confidence, safe_int(record.get("confidence"), 0))
            for narrative_name in unique_text_list(record.get("narrative_membership") or ["Unclassified"]):
                scope_narratives.add(narrative_name)

        group["scope_source_count"] = len(scope_source_names)
        group["scope_narratives"] = scope_narratives
        group["mention_count"] = len(scope_records)
        group["source_count"] = len(scope_source_names)
        group["promotion_confidence"] = scope_confidence
        group["entity_priority"] = group.get("entity_priority", 0.0)
        group["first_seen_key"] = record_scope_key(
            {"partition_date": group["first_seen_date"].isoformat() if group["first_seen_date"] else ""},
            scope,
        )
        group["last_seen_key"] = record_scope_key(
            {"partition_date": group["last_seen_date"].isoformat() if group["last_seen_date"] else ""},
            scope,
        )

    return narrative_groups, entity_groups


def narrative_sort_key(group):
    return (
        -safe_float(group.get("narrative_priority"), 0.0),
        -safe_int(group.get("promotion_confidence"), 0),
        -safe_int(group.get("source_count"), 0),
        -safe_float(group.get("entity_priority"), 0.0),
        -safe_int(group.get("mention_count"), 0),
        normalize_text(group.get("narrative_name")).lower(),
    )


def entity_sort_key(group):
    return (
        -safe_float(group.get("entity_priority"), 0.0),
        -safe_int(group.get("source_count"), 0),
        -safe_int(group.get("promotion_confidence"), 0),
        -safe_int(group.get("mention_count"), 0),
        normalize_text(group.get("entity_name")).lower(),
    )


def format_entity_list(values, limit=3):
    items = unique_text_list(values)

    if not items:
        return "none"

    return ", ".join(items[:limit])


def build_group_line(group):
    return (
        f"- `{group['narrative_name']}` | priority `{group.get('narrative_priority', 0):g}` "
        f"| confidence `{group.get('promotion_confidence', 0)}` "
        f"| sources `{group.get('source_count', 0)}` "
        f"| entities `{format_entity_list(group.get('entity_names', []))}` "
        f"| records `{group.get('mention_count', 0)}`"
    )


def build_entity_line(group):
    return (
        f"- `{group['entity_name']}` | priority `{group.get('entity_priority', 0):g}` "
        f"| confidence `{group.get('promotion_confidence', 0)}` "
        f"| sources `{group.get('source_count', 0)}` "
        f"| narratives `{format_entity_list(group.get('scope_narratives', []))}` "
        f"| records `{group.get('mention_count', 0)}`"
    )


def build_new_signal_line(group):
    first_seen = group.get("first_seen_date").isoformat() if group.get("first_seen_date") else "unknown"
    top_titles = []

    for record in sorted(
        group.get("scope_records", []),
        key=lambda item: (
            -safe_int(item.get("confidence"), 0),
            record_partition_date(item).isoformat() if record_partition_date(item) else "",
            normalize_text(item.get("title")).lower(),
        ),
    ):
        title = normalize_text(record.get("title") or record.get("markdown_title"))
        if title:
            top_titles.append(title)

    titles_text = format_entity_list(top_titles, limit=2)

    return (
        f"- `{group['narrative_name']}` first seen `{first_seen}` "
        f"via `{titles_text}` | confidence `{group.get('promotion_confidence', 0)}` "
        f"| sources `{group.get('source_count', 0)}`"
    )


def build_reinforced_line(group):
    first_seen = group.get("first_seen_date").isoformat() if group.get("first_seen_date") else "unknown"
    return (
        f"- `{group['narrative_name']}` reinforced since `{first_seen}` "
        f"with `{group.get('source_count', 0)}` sources and confidence `{group.get('promotion_confidence', 0)}` "
        f"| entities `{format_entity_list(group.get('entity_names', []))}`"
    )


def build_question_line(group):
    source_count = group.get("source_count", 0)
    confidence = group.get("promotion_confidence", 0)

    if source_count <= 1:
        return f"- Can `{group['narrative_name']}` be corroborated by a second source?"

    if confidence < 85:
        return f"- What additional evidence would raise conviction on `{group['narrative_name']}`?"

    return f"- What downstream confirmation should Midas look for on `{group['narrative_name']}`?"


def build_followup_line(group):
    return (
        f"- Review `{group['narrative_name']}` for Midas: `{group.get('source_count', 0)}` sources, "
        f"confidence `{group.get('promotion_confidence', 0)}`, entity priority `{group.get('entity_priority', 0):g}`."
    )


def render_section(title, lines):
    output = [f"## {title}"]

    if not lines:
        output.append("- None.")
        return "\n".join(output)

    output.extend(lines)
    return "\n".join(output)


def build_summary_lines(scope_name, scope_date, scope_records, narrative_groups, entity_groups):
    unique_sources = sorted(
        {
            normalize_text(record.get("source") or record.get("source_name") or "Unknown")
            for record in scope_records
        },
        key=str.lower,
    )
    unique_narratives = sorted(
        {narrative for record in scope_records for narrative in unique_text_list(record.get("narrative_membership") or ["Unclassified"])},
        key=str.lower,
    )
    top_narrative = None
    if narrative_groups:
        scoped_narratives = [
            group for group in narrative_groups.values() if group.get("mention_count", 0) > 0
        ]
        if scoped_narratives:
            top_narrative = sorted(scoped_narratives, key=narrative_sort_key)[0]

    lines = [
        f"- Scope: `{scope_name}` `{scope_date}`.",
        f"- Coverage: `{len(scope_records)}` memories, `{len(unique_narratives)}` narratives, `{len(unique_sources)}` sources.",
    ]

    if top_narrative:
        lines.append(
            f"- Top narrative: `{top_narrative['narrative_name']}` "
            f"with confidence `{top_narrative.get('promotion_confidence', 0)}` "
            f"and `{top_narrative.get('source_count', 0)}` sources."
        )

    if entity_groups:
        scoped_entities = [
            group for group in entity_groups.values() if group.get("mention_count", 0) > 0
        ]

        if scoped_entities:
            top_entity = sorted(scoped_entities, key=entity_sort_key)[0]
            lines.append(
                f"- Top entity: `{top_entity['entity_name']}` "
                f"with priority `{top_entity.get('entity_priority', 0):g}` "
                f"and `{top_entity.get('source_count', 0)}` sources."
            )

    return lines


def build_synthesis_markdown(scope_name, scope_date, scope_records, narrative_groups, entity_groups, target_date):
    week_start, week_end = week_window(target_date)
    scope_window = scope_date

    if scope_name == "weekly":
        scope_window = f"{scope_date} ({week_start} to {week_end})"

    narrative_list = [
        group
        for group in sorted(narrative_groups.values(), key=narrative_sort_key)
        if group.get("mention_count", 0) > 0
    ]
    entity_list = [
        group
        for group in sorted(entity_groups.values(), key=entity_sort_key)
        if group.get("mention_count", 0) > 0
    ]

    new_narratives = [
        group
        for group in narrative_list
        if group.get("first_seen_key") == (iso_week_key(target_date) if scope_name == "weekly" else scope_date)
    ]
    reinforced_narratives = [
        group
        for group in narrative_list
        if group.get("first_seen_key") != (iso_week_key(target_date) if scope_name == "weekly" else scope_date)
        and group.get("mention_count", 0) > 0
    ]
    followups = [
        group
        for group in narrative_list
        if group.get("promotion_confidence", 0) >= 90 and group.get("source_count", 0) >= 2
    ]
    open_questions = [
        group
        for group in narrative_list
        if group.get("source_count", 0) <= 1 or group.get("promotion_confidence", 0) < 85
    ]

    high_priority_entities = [
        group
        for group in entity_list
        if group.get("source_count", 0) > 1 or group.get("entity_priority", 0) >= 1
    ]

    summary_lines = build_summary_lines(scope_name, scope_window, scope_records, narrative_groups, entity_groups)

    markdown_lines = [
        "# Hermes Synthesis Memo",
        "",
        render_section(
            "Executive Summary",
            summary_lines[:3] if summary_lines else ["- None."],
        ),
        "",
        render_section(
            "Top Narratives",
            [build_group_line(group) for group in narrative_list[:5]],
        ),
        "",
        render_section(
            "New Signals",
            [build_new_signal_line(group) for group in new_narratives[:5]],
        ),
        "",
        render_section(
            "Reinforced Signals",
            [build_reinforced_line(group) for group in reinforced_narratives[:5]],
        ),
        "",
        render_section(
            "Portfolio / Watchlist Relevance",
            [build_entity_line(group) for group in high_priority_entities[:5]],
        ),
        "",
        render_section(
            "Open Questions",
            [build_question_line(group) for group in open_questions[:5]],
        ),
        "",
        render_section(
            "Suggested Follow-ups for Midas",
            [build_followup_line(group) for group in followups[:5]],
        ),
        "",
    ]

    return "\n".join(markdown_lines).strip() + "\n"


def write_text_if_changed(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == content:
            return False

    path.write_text(content, encoding="utf-8")
    return True


def build_synthesis(
    wiki_root=DEFAULT_WIKI_ROOT,
    index_path=DEFAULT_INDEX_PATH,
    narrative_summary_path=DEFAULT_NARRATIVE_SUMMARY_PATH,
    target_date="",
):
    wiki_root = Path(wiki_root)
    index_path = Path(index_path)
    narrative_summary_path = Path(narrative_summary_path)

    index_records = load_index_records(index_path)
    target_date_value = resolve_target_date(index_records, target_date)
    summary, narrative_priority_map, entity_priority_map = load_narrative_summary_map(
        narrative_summary_path
    )
    _ = summary

    wiki_records = load_wiki_records(wiki_root, index_records)
    scope_date = target_date_value.isoformat()
    daily_groups, daily_entities = group_records(
        wiki_records,
        "daily",
        target_date_value,
        narrative_priority_map,
        entity_priority_map,
    )
    weekly_groups, weekly_entities = group_records(
        wiki_records,
        "weekly",
        target_date_value,
        narrative_priority_map,
        entity_priority_map,
    )

    daily_markdown = build_synthesis_markdown(
        "daily",
        scope_date,
        [record for record in wiki_records if scope_matches(record, target_date_value, "daily")],
        daily_groups,
        daily_entities,
        target_date_value,
    )
    weekly_key = iso_week_key(target_date_value)
    weekly_markdown = build_synthesis_markdown(
        "weekly",
        weekly_key,
        [record for record in wiki_records if scope_matches(record, target_date_value, "weekly")],
        weekly_groups,
        weekly_entities,
        target_date_value,
    )

    daily_output_path = wiki_root / "synthesis" / "daily" / f"{scope_date}.md"
    weekly_output_path = wiki_root / "synthesis" / "weekly" / f"{weekly_key}.md"

    daily_written = write_text_if_changed(daily_output_path, daily_markdown)
    weekly_written = write_text_if_changed(weekly_output_path, weekly_markdown)

    daily_scope_records = [record for record in wiki_records if scope_matches(record, target_date_value, "daily")]
    weekly_scope_records = [record for record in wiki_records if scope_matches(record, target_date_value, "weekly")]

    return {
        "target_date": scope_date,
        "target_week": weekly_key,
        "index_record_count": len(index_records),
        "wiki_record_count": len(wiki_records),
        "daily_scope_record_count": len(daily_scope_records),
        "weekly_scope_record_count": len(weekly_scope_records),
        "daily_output_path": daily_output_path,
        "weekly_output_path": weekly_output_path,
        "daily_written": daily_written,
        "weekly_written": weekly_written,
        "daily_markdown": daily_markdown,
        "weekly_markdown": weekly_markdown,
    }


def main():
    parser = argparse.ArgumentParser(description="Build deterministic Hermes synthesis memos from AEON memory.")
    parser.add_argument(
        "--wiki-root",
        default=str(DEFAULT_WIKI_ROOT),
        help="Hermes wiki root that contains aeon memory artifacts.",
    )
    parser.add_argument(
        "--index-path",
        default=str(DEFAULT_INDEX_PATH),
        help="Path to workspace/wiki/meta/aeon_index.jsonl.",
    )
    parser.add_argument(
        "--narrative-summary-path",
        default=str(DEFAULT_NARRATIVE_SUMMARY_PATH),
        help="Optional narrative summary JSON used for priority hints.",
    )
    parser.add_argument(
        "--target-date",
        default="",
        help="Target date for daily synthesis. Defaults to the latest AEON partition date.",
    )

    args = parser.parse_args()

    result = build_synthesis(
        wiki_root=Path(args.wiki_root),
        index_path=Path(args.index_path),
        narrative_summary_path=Path(args.narrative_summary_path),
        target_date=args.target_date,
    )

    print(
        "Generated Hermes synthesis for "
        f"{result['target_date']} and {result['target_week']}."
    )


if __name__ == "__main__":
    main()
