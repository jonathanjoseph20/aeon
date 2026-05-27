import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_WIKI_ROOT = REPO_ROOT / "workspace" / "wiki"
DEFAULT_INDEX_PATH = DEFAULT_WIKI_ROOT / "meta" / "aeon_index.jsonl"
DEFAULT_NARRATIVE_SUMMARY_PATH = REPO_ROOT / "data" / "processed" / "narrative_summary.json"
DEFAULT_FALLBACK_DATE = "1970-01-01"
DEFAULT_MAX_TASKS = 12
TASK_EXECUTION_STATES = (
    "pending",
    "acknowledged",
    "in_progress",
    "completed",
    "failed",
    "ignored",
)
TASK_TERMINAL_STATES = {"completed", "failed", "ignored"}
TASK_STATE_TRANSITIONS = {
    "pending": {"pending", "acknowledged", "in_progress", "completed", "failed", "ignored"},
    "acknowledged": {"acknowledged", "in_progress", "completed", "failed", "ignored"},
    "in_progress": {"in_progress", "completed", "failed", "ignored"},
    "completed": {"completed"},
    "failed": {"failed"},
    "ignored": {"ignored"},
}

NARRATIVE_SECTION_TITLES = (
    "Top Narratives",
    "New Signals",
    "Reinforced Signals",
    "Open Questions",
    "Suggested Follow-ups for Midas",
)

ENTITY_SECTION_TITLES = ("Portfolio / Watchlist Relevance",)

IMPLEMENTATION_KEYWORDS = (
    "build",
    "deploy",
    "implementation",
    "integration",
    "launch",
    "rollout",
    "ship",
    "workflow",
    "automation",
    "pipeline",
)


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


def append_jsonl(path, records):
    if not records:
        return

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def normalize_text(value):
    text = str(value or "")
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_task_state(value, default="pending"):
    state = normalize_text(value).lower()

    if state in TASK_EXECUTION_STATES:
        return state

    return default


def task_state_allows_transition(current_state, next_state):
    current = normalize_task_state(current_state)
    target = normalize_task_state(next_state)

    return target in TASK_STATE_TRANSITIONS.get(current, {current})


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


def load_markdown_text(path):
    path = Path(path)

    if not path.exists():
        return ""

    return path.read_text(encoding="utf-8")


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


def extract_backticked_name(line):
    matches = re.findall(r"`([^`]+)`", line)

    if not matches:
        return ""

    return normalize_text(matches[0])


def extract_section_items(markdown_text, section_title):
    sections = parse_markdown_sections(markdown_text)
    section_body = sections.get(section_title, "")
    items = []

    for raw_line in section_body.splitlines():
        line = raw_line.strip()

        if not line.startswith("-"):
            continue

        if line == "- None.":
            continue

        value = extract_backticked_name(line)

        if value:
            items.append(value)

    return unique_text_list(items)


def discover_target_date(daily_dir, index_records, target_date=""):
    parsed = parse_iso_date(target_date)

    if parsed is not None:
        return parsed

    daily_dir = Path(daily_dir)
    daily_dates = []

    if daily_dir.exists():
        for path in daily_dir.glob("*.md"):
            parsed = parse_iso_date(path.stem)

            if parsed is not None:
                daily_dates.append(parsed)

    if daily_dates:
        return max(daily_dates)

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


def load_summary_maps(narrative_summary_path):
    summary = load_json(narrative_summary_path) or {}

    narrative_map = {}
    for narrative in summary.get("narratives", []) or []:
        name = normalize_text(narrative.get("narrative_name"))

        if not name:
            continue

        narrative_map[name] = dict(narrative)

    for narrative in summary.get("top_narratives", []) or []:
        name = normalize_text(narrative.get("narrative_name"))

        if not name:
            continue

        existing = narrative_map.get(name, {})
        merged = dict(existing)
        merged.update(narrative)
        narrative_map[name] = merged

    entity_map = {}
    for entity in summary.get("entities", []) or []:
        name = normalize_text(entity.get("canonical_name") or entity.get("entity_name"))

        if not name:
            continue

        entity_map[name] = dict(entity)

    return summary, narrative_map, entity_map


def build_index_maps(index_records):
    narrative_to_records = defaultdict(list)
    entity_to_records = defaultdict(list)

    for record in index_records:
        narrative_names = unique_text_list(record.get("narrative_membership") or [])

        if not narrative_names:
            narrative_names = ["Unclassified"]

        entity_names = unique_text_list(record.get("canonical_entities") or [])

        for narrative_name in narrative_names:
            narrative_to_records[narrative_name].append(record)

        for entity_name in entity_names:
            entity_to_records[entity_name].append(record)

    return narrative_to_records, entity_to_records


def source_name_for_record(record):
    return normalize_text(record.get("source") or record.get("source_name") or "Unknown")


def record_verticals(record):
    return unique_text_list(record.get("verticals") or [])


def has_implementation_signal(text_values):
    haystack = " ".join(normalize_text(value).lower() for value in text_values if value)

    return any(keyword in haystack for keyword in IMPLEMENTATION_KEYWORDS)


def select_top_entities_from_records(records, entity_map, limit=5):
    counts = Counter()

    for record in records:
        for entity_name in unique_text_list(record.get("canonical_entities") or []):
            counts[entity_name] += 1

    ranked = sorted(
        counts.items(),
        key=lambda item: (
            -item[1],
            -safe_float(entity_map.get(item[0], {}).get("priority_score"), 0.0),
            normalize_text(item[0]).lower(),
        ),
    )

    return [name for name, _count in ranked[:limit]]


def select_top_narratives_from_records(records, narrative_map, limit=4):
    counts = Counter()

    for record in records:
        for narrative_name in unique_text_list(record.get("narrative_membership") or []):
            counts[narrative_name] += 1

    ranked = sorted(
        counts.items(),
        key=lambda item: (
            -item[1],
            -safe_float(narrative_map.get(item[0], {}).get("priority_score"), 0.0),
            normalize_text(item[0]).lower(),
        ),
    )

    return [name for name, _count in ranked[:limit]]


def collect_markdown_focus(daily_markdown, weekly_markdown):
    narrative_names = []
    entity_names = []

    for markdown_text in (daily_markdown, weekly_markdown):
        if not markdown_text:
            continue

        for section_title in NARRATIVE_SECTION_TITLES:
            narrative_names.extend(extract_section_items(markdown_text, section_title))

        for section_title in ENTITY_SECTION_TITLES:
            entity_names.extend(extract_section_items(markdown_text, section_title))

    return unique_text_list(narrative_names), unique_text_list(entity_names)


def related_record_sources(records):
    return sorted({source_name_for_record(record) for record in records}, key=str.lower)


def related_record_verticals(records):
    verticals = []

    for record in records:
        verticals.extend(record_verticals(record))

    return unique_text_list(verticals)


def related_record_titles(records):
    titles = []

    for record in records:
        title = normalize_text(record.get("title") or record.get("subject") or record.get("markdown_title"))

        if title:
            titles.append(title)

    return unique_text_list(titles)


def repo_relative_path(path):
    if not path:
        return ""

    path = Path(path)

    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def evidence_record_key(record):
    return normalize_text(
        record.get("memory_id")
        or record.get("evidence_id")
        or record.get("file_path")
        or record.get("title")
    ).lower()


def build_evidence_record(record):
    return {
        "evidence_id": normalize_text(
            record.get("memory_id")
            or record.get("file_path")
            or record.get("title")
        ),
        "memory_id": normalize_text(record.get("memory_id")),
        "file_path": normalize_text(record.get("file_path")),
        "title": normalize_text(record.get("title") or record.get("subject")),
        "source": source_name_for_record(record),
        "source_type": normalize_text(record.get("source_type")),
        "source_url": normalize_text(record.get("source_url")),
        "timestamp": normalize_text(record.get("timestamp")),
        "partition_date": normalize_text(record.get("partition_date")),
        "canonical_entities": unique_text_list(record.get("canonical_entities") or []),
        "narrative_membership": unique_text_list(record.get("narrative_membership") or []),
    }


def evidence_sort_key(record):
    timestamp = parse_iso_datetime(record.get("timestamp"))
    return (
        timestamp.isoformat() if timestamp is not None else "",
        normalize_text(record.get("memory_id") or record.get("evidence_id")).lower(),
        normalize_text(record.get("title")).lower(),
    )


def build_task_lineage(task_id, task_key, category, candidate_kind, narrative_name, canonical_entities, evidence_records, daily_path, weekly_path):
    deduped = {}

    for record in evidence_records or []:
        key = evidence_record_key(record)

        if not key:
            continue

        if key not in deduped:
            deduped[key] = dict(record)

    ordered_evidence = sorted(deduped.values(), key=evidence_sort_key)
    evidence_ids = unique_text_list(
        [
            normalize_text(record.get("memory_id") or record.get("evidence_id"))
            for record in ordered_evidence
        ]
    )
    synthesis_refs = unique_text_list(
        [repo_relative_path(daily_path), repo_relative_path(weekly_path)]
    )

    entities = []

    for entity_name in unique_text_list(canonical_entities):
        entity_ids = []

        for record in ordered_evidence:
            if entity_name in unique_text_list(record.get("canonical_entities") or []):
                entity_ids.append(normalize_text(record.get("memory_id") or record.get("evidence_id")))

        entities.append(
            {
                "name": entity_name,
                "source_ids": unique_text_list(entity_ids),
            }
        )

    return {
        "task_id": task_id,
        "task_key": task_key,
        "category": category,
        "narrative": {
            "name": narrative_name,
            "kind": candidate_kind,
            "source_ids": evidence_ids,
            "synthesis_refs": synthesis_refs,
        },
        "entities": entities,
        "source_evidence": ordered_evidence,
    }


def build_execution_history_entry(task_id, state, timestamp, source, note="", update_id=""):
    entry = {
        "state": normalize_task_state(state),
        "timestamp": normalize_text(timestamp),
        "source": normalize_text(source),
    }

    task_identifier = normalize_text(task_id)

    if task_identifier:
        entry["task_id"] = task_identifier
        entry["task_key"] = task_identifier

    if note:
        entry["note"] = normalize_text(note)

    if update_id:
        entry["update_id"] = normalize_text(update_id)

    return entry


def build_task_completion_memory_id(task_key, completed_at):
    completed_at_text = normalize_text(completed_at)[:10] or DEFAULT_FALLBACK_DATE
    fingerprint = f"{normalize_text(task_key)}\n{normalize_text(completed_at)}"
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]
    return f"task-completion-{completed_at_text}-{digest}"


def build_completion_memory_record(task, update, completed_at):
    task_id = normalize_text(task.get("task_id"))
    task_key = normalize_text(task.get("task_key") or task_id)
    completion_memory_id = build_task_completion_memory_id(task_key, completed_at)
    lineage = task.get("lineage") or {}
    narrative = lineage.get("narrative") or {}

    return {
        "memory_id": completion_memory_id,
        "title": f"Completed task: {normalize_text(task.get('narrative') or narrative.get('name') or task_id)}",
        "source": "Midas task execution",
        "source_type": "task_execution",
        "timestamp": normalize_text(completed_at),
        "indexed_at": normalize_text(completed_at),
        "partition_date": normalize_text(completed_at)[:10] or DEFAULT_FALLBACK_DATE,
        "task_id": task_id,
        "task_key": task_key,
        "task_date": normalize_text(task.get("task_date")),
        "task_state": "completed",
        "task_category": normalize_text(task.get("category")),
        "task_narrative": normalize_text(task.get("narrative") or narrative.get("name")),
        "task_update_id": normalize_text(update.get("update_id")),
        "task_update_state": normalize_task_state(update.get("state")),
        "task_update_source": normalize_text(update.get("source") or update.get("actor") or "midas"),
        "canonical_entities": unique_text_list(task.get("canonical_entities") or []),
        "narrative_membership": unique_text_list(
            [normalize_text(task.get("narrative") or narrative.get("name"))]
        ),
        "synthesis_refs": unique_text_list(
            task.get("synthesis_refs") or narrative.get("synthesis_refs") or []
        ),
        "lineage": lineage,
        "result": normalize_text(update.get("result") or update.get("note")),
    }


def build_task_id(category, narrative, canonical_entities):
    canonical_part = "|".join(sorted(normalize_text(value).lower() for value in canonical_entities))
    fingerprint = normalize_text(category).lower() + "\n" + normalize_text(narrative).lower() + "\n" + canonical_part
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]
    return f"task-{digest}"


def trend_priority_bonus(trend_status):
    mapping = {
        "new": 18,
        "rising": 16,
        "stable": 8,
        "fading": -8,
    }

    return mapping.get(normalize_text(trend_status).lower(), 6)


def category_priority_bonus(category):
    mapping = {
        "opportunity": 10,
        "risk": 9,
        "thesis_update": 8,
        "implementation": 7,
        "research": 6,
        "monitor": 2,
    }

    return mapping.get(normalize_text(category).lower(), 5)


def compute_priority(base_priority, trend_status, source_count, promotion_count, source_diversity, portfolio_relevant, category):
    score = 10
    score += min(40, int(round(safe_float(base_priority, 0.0) / 8.0)))
    score += trend_priority_bonus(trend_status)
    score += min(18, safe_int(source_count, 0) * 3)
    score += min(16, safe_int(promotion_count, 0) * 4)
    score += min(10, safe_int(source_diversity, 0) * 2)
    score += 10 if portfolio_relevant else 0
    score += category_priority_bonus(category)
    return max(1, min(100, int(round(score))))


def compute_confidence(trend_status, source_count, promotion_count, source_diversity, portfolio_relevant):
    score = 55
    score += min(18, safe_int(source_count, 0) * 2)
    score += min(12, safe_int(promotion_count, 0) * 3)
    score += min(10, safe_int(source_diversity, 0) * 2)
    score += {
        "new": 8,
        "rising": 6,
        "stable": 4,
        "fading": 0,
    }.get(normalize_text(trend_status).lower(), 2)
    score += 4 if portfolio_relevant else 0
    return max(1, min(99, int(round(score))))


def category_for_narrative(narrative_name, trend_status, source_count, promotion_count, portfolio_relevant, base_priority, has_implementation_signal_flag):
    name = normalize_text(narrative_name).lower()

    if has_implementation_signal_flag or any(keyword in name for keyword in IMPLEMENTATION_KEYWORDS):
        return "implementation"

    if normalize_text(trend_status).lower() == "fading" and portfolio_relevant:
        return "risk"

    if normalize_text(trend_status).lower() in {"new", "rising"} and promotion_count >= 2:
        if portfolio_relevant or base_priority >= 75:
            return "opportunity"
        return "research"

    if promotion_count >= 2 and source_count >= 3 and base_priority >= 50:
        return "thesis_update"

    if source_count <= 1:
        return "monitor"

    if portfolio_relevant and base_priority >= 70:
        return "thesis_update"

    return "research"


def category_for_entity(entity_name, trend_status, source_count, promotion_count, portfolio_relevant, base_priority, has_implementation_signal_flag):
    name = normalize_text(entity_name).lower()

    if has_implementation_signal_flag or any(keyword in name for keyword in IMPLEMENTATION_KEYWORDS):
        return "implementation"

    if normalize_text(trend_status).lower() == "fading" and portfolio_relevant:
        return "risk"

    if source_count <= 1:
        return "monitor"

    if source_count >= 3 and promotion_count >= 1:
        return "thesis_update"

    if normalize_text(trend_status).lower() in {"new", "rising"} and (portfolio_relevant or base_priority >= 80):
        return "opportunity"

    if base_priority >= 100 and portfolio_relevant:
        return "opportunity"

    return "research"


def choose_suggested_action(category, narrative_name, canonical_entities):
    entity_text = ", ".join(canonical_entities[:3]) if canonical_entities else "the linked entities"

    if category == "opportunity":
        return f"Have Midas validate whether `{narrative_name}` should move from watchlist to active coverage and confirm the next catalyst."

    if category == "risk":
        return f"Have Midas assess whether `{narrative_name}` introduces downside or exposure that should be reduced or hedged."

    if category == "thesis_update":
        return f"Have Midas refresh the thesis memo for `{narrative_name}` using the new source diversity and entity mix."

    if category == "implementation":
        return f"Have Midas break `{narrative_name}` into the next executable step and assign the smallest viable owner."

    if category == "monitor":
        return f"Have Midas keep `{narrative_name}` on watch and wait for a second source or a trend change."

    return f"Have Midas do a focused research pass on `{narrative_name}` and confirm the implications for {entity_text}."


def build_reason(category, narrative_name, source_count, promotion_count, source_diversity, canonical_entities, daily_path, weekly_path, trend_status, portfolio_relevant):
    entity_text = ", ".join(canonical_entities[:5]) if canonical_entities else "none"
    refs = []

    for path in (daily_path, weekly_path):
        if path and Path(path).exists():
            try:
                refs.append(str(Path(path).relative_to(REPO_ROOT)))
            except ValueError:
                refs.append(str(Path(path)))

    refs_text = ", ".join(unique_text_list(refs)) if refs else "Hermes synthesis inputs"
    portfolio_text = "yes" if portfolio_relevant else "no"

    return (
        f"{normalize_text(trend_status).capitalize() or 'Stable'} `{narrative_name}` maps to `{category}` "
        f"with `{source_count}` sources, `{promotion_count}` promotions, and `{source_diversity}` distinct sources. "
        f"Canonical entities: {entity_text}. Portfolio relevance: {portfolio_text}. "
        f"Hermes synthesis refs: {refs_text}."
    )


def merge_candidate(dest, candidate):
    dest["source_count"] = max(safe_int(dest.get("source_count"), 0), safe_int(candidate.get("source_count"), 0))
    dest["promotion_count"] = max(safe_int(dest.get("promotion_count"), 0), safe_int(candidate.get("promotion_count"), 0))
    dest["priority"] = max(safe_int(dest.get("priority"), 0), safe_int(candidate.get("priority"), 0))
    dest["confidence"] = max(safe_int(dest.get("confidence"), 0), safe_int(candidate.get("confidence"), 0))
    dest["source_diversity"] = max(
        safe_int(dest.get("source_diversity"), 0),
        safe_int(candidate.get("source_diversity"), 0),
    )
    dest["base_priority"] = max(
        safe_float(dest.get("base_priority"), 0.0),
        safe_float(candidate.get("base_priority"), 0.0),
    )
    dest["portfolio_relevant"] = bool(dest.get("portfolio_relevant") or candidate.get("portfolio_relevant"))
    dest["trend_status"] = dest.get("trend_status") or candidate.get("trend_status")
    dest["candidate_kind"] = dest.get("candidate_kind") or candidate.get("candidate_kind")

    dest_entities = unique_text_list(dest.get("canonical_entities") or [])
    candidate_entities = unique_text_list(candidate.get("canonical_entities") or [])
    dest["canonical_entities"] = unique_text_list(dest_entities + candidate_entities)

    dest_refs = set(dest.get("_source_refs") or [])
    dest_refs.update(candidate.get("_source_refs") or [])
    dest["_source_refs"] = sorted(dest_refs)

    dest_evidence = {}

    for record in dest.get("_evidence_records") or []:
        key = evidence_record_key(record)

        if key and key not in dest_evidence:
            dest_evidence[key] = dict(record)

    for record in candidate.get("_evidence_records") or []:
        key = evidence_record_key(record)

        if key and key not in dest_evidence:
            dest_evidence[key] = dict(record)

    dest["_evidence_records"] = sorted(dest_evidence.values(), key=evidence_sort_key)

    return dest


def dedupe_candidates(candidates):
    deduped = {}

    for candidate in candidates:
        key = (
            normalize_text(candidate.get("category")).lower(),
            normalize_text(candidate.get("narrative")).lower(),
            tuple(sorted(normalize_text(entity).lower() for entity in unique_text_list(candidate.get("canonical_entities") or []))),
        )

        existing = deduped.get(key)

        if existing is None:
            deduped[key] = dict(candidate)
            continue

        deduped[key] = merge_candidate(existing, candidate)

    return list(deduped.values())


def finalize_task(candidate):
    source_refs = unique_text_list(candidate.get("_source_refs") or [])
    evidence_records = candidate.get("_evidence_records") or []
    task_id = build_task_id(
        candidate["category"],
        candidate["narrative"],
        candidate.get("canonical_entities") or [],
    )
    task_date = normalize_text(candidate.get("created_at"))[:10] or DEFAULT_FALLBACK_DATE
    task_key = f"{task_date}:{task_id}"
    lineage = build_task_lineage(
        task_id,
        task_key,
        candidate["category"],
        candidate.get("candidate_kind") or "narrative",
        candidate["narrative"],
        candidate.get("canonical_entities") or [],
        evidence_records,
        candidate.get("daily_path"),
        candidate.get("weekly_path"),
    )
    synthesis_refs = unique_text_list(
        [repo_relative_path(candidate.get("daily_path")), repo_relative_path(candidate.get("weekly_path"))]
    )
    task = {
        "task_id": task_id,
        "created_at": candidate["created_at"],
        "priority": safe_int(candidate.get("priority"), 0),
        "category": candidate["category"],
        "narrative": candidate["narrative"],
        "canonical_entities": unique_text_list(candidate.get("canonical_entities") or []),
        "reason": build_reason(
            candidate["category"],
            candidate["narrative"],
            candidate.get("source_count", 0),
            candidate.get("promotion_count", 0),
            candidate.get("source_diversity", 0),
            candidate.get("canonical_entities") or [],
            candidate.get("daily_path"),
            candidate.get("weekly_path"),
            candidate.get("trend_status"),
            bool(candidate.get("portfolio_relevant")),
        ),
        "suggested_action": candidate["suggested_action"],
        "source_count": safe_int(candidate.get("source_count"), 0),
        "promotion_count": safe_int(candidate.get("promotion_count"), 0),
        "confidence": safe_int(candidate.get("confidence"), 0),
        "status": "open",
        "task_date": task_date,
        "task_key": task_key,
        "execution_state": "pending",
        "execution_state_updated_at": candidate["created_at"],
        "execution_history": [
            build_execution_history_entry(
                task_key,
                "pending",
                candidate["created_at"],
                "hermes",
                "Task created from deterministic synthesis.",
                f"{task_key}::created::{candidate['created_at']}",
            )
        ],
        "lineage": lineage,
        "synthesis_refs": synthesis_refs,
        "source_evidence_count": len(lineage.get("source_evidence") or []),
    }

    if source_refs:
        task["reason"] = f"{task['reason']} Source refs: {', '.join(source_refs)}."

    return task


def build_narrative_candidate(
    narrative_name,
    narrative_map,
    narrative_records,
    entity_map,
    daily_path,
    weekly_path,
    created_at,
):
    summary = dict(narrative_map.get(narrative_name, {}))
    records = narrative_records.get(narrative_name, [])

    source_names = related_record_sources(records)
    source_diversity = len(source_names)
    source_count = safe_int(summary.get("source_count"), source_diversity)
    promotion_count = safe_int(summary.get("promotion_count"), 0)
    trend_status = normalize_text(summary.get("trend_status") or "stable")
    narrative_priority = safe_float(summary.get("priority_score"), 0.0)

    canonical_entities = select_top_entities_from_records(records, entity_map, limit=5)

    if not canonical_entities:
        canonical_entities = unique_text_list(summary.get("canonical_entities") or [])[:5]

    entity_priority = max(
        [safe_float(entity_map.get(entity, {}).get("priority_score"), 0.0) for entity in canonical_entities]
        or [0.0]
    )
    base_priority = max(narrative_priority, entity_priority)
    verticals = related_record_verticals(records)
    portfolio_relevant = "Portfolio" in verticals or any(
        "Portfolio" in unique_text_list(entity_map.get(entity, {}).get("verticals") or [])
        for entity in canonical_entities
    )
    implementation_flag = has_implementation_signal([narrative_name] + related_record_titles(records))
    category = category_for_narrative(
        narrative_name,
        trend_status,
        source_count,
        promotion_count,
        portfolio_relevant,
        base_priority,
        implementation_flag,
    )
    priority = compute_priority(
        base_priority,
        trend_status,
        source_count,
        promotion_count,
        source_diversity,
        portfolio_relevant,
        category,
    )
    confidence = compute_confidence(
        trend_status,
        source_count,
        promotion_count,
        source_diversity,
        portfolio_relevant,
    )

    return {
        "created_at": created_at,
        "category": category,
        "narrative": narrative_name,
        "canonical_entities": canonical_entities,
        "source_count": source_count,
        "promotion_count": promotion_count,
        "source_diversity": source_diversity,
        "trend_status": trend_status,
        "portfolio_relevant": portfolio_relevant,
        "priority": priority,
        "confidence": confidence,
        "suggested_action": choose_suggested_action(category, narrative_name, canonical_entities),
        "daily_path": daily_path,
        "weekly_path": weekly_path,
        "_source_refs": [str(path) for path in (daily_path, weekly_path) if path],
        "_evidence_records": [build_evidence_record(record) for record in records],
        "base_priority": base_priority,
        "candidate_kind": "narrative",
    }


def build_entity_candidate(
    entity_name,
    entity_map,
    entity_records,
    narrative_map,
    daily_path,
    weekly_path,
    created_at,
):
    summary = dict(entity_map.get(entity_name, {}))
    records = entity_records.get(entity_name, [])

    source_names = related_record_sources(records)
    source_diversity = len(source_names)
    source_count = safe_int(summary.get("source_count"), source_diversity)
    promotion_count = safe_int(summary.get("promotion_count"), 0)
    trend_status = normalize_text(summary.get("trend_status") or "stable")
    base_priority = safe_float(summary.get("priority_score"), 0.0)
    canonical_entities = unique_text_list([entity_name] + select_top_entities_from_records(records, entity_map, limit=4))

    if not canonical_entities:
        canonical_entities = [entity_name]

    verticals = unique_text_list(summary.get("verticals") or []) + related_record_verticals(records)
    portfolio_relevant = "Portfolio" in unique_text_list(verticals)
    implementation_flag = has_implementation_signal([entity_name] + related_record_titles(records))
    category = category_for_entity(
        entity_name,
        trend_status,
        source_count,
        promotion_count,
        portfolio_relevant,
        base_priority,
        implementation_flag,
    )
    priority = compute_priority(
        base_priority,
        trend_status,
        source_count,
        promotion_count,
        source_diversity,
        portfolio_relevant,
        category,
    )
    confidence = compute_confidence(
        trend_status,
        source_count,
        promotion_count,
        source_diversity,
        portfolio_relevant,
    )

    related_narratives = select_top_narratives_from_records(records, narrative_map, limit=3)
    if related_narratives:
        narrative_name = related_narratives[0]
    else:
        narrative_name = entity_name

    return {
        "created_at": created_at,
        "category": category,
        "narrative": entity_name,
        "canonical_entities": canonical_entities,
        "source_count": source_count,
        "promotion_count": promotion_count,
        "source_diversity": source_diversity,
        "trend_status": trend_status,
        "portfolio_relevant": portfolio_relevant,
        "priority": priority,
        "confidence": confidence,
        "suggested_action": choose_suggested_action(category, entity_name, canonical_entities),
        "daily_path": daily_path,
        "weekly_path": weekly_path,
        "_source_refs": [str(path) for path in (daily_path, weekly_path) if path],
        "_evidence_records": [build_evidence_record(record) for record in records],
        "base_priority": base_priority,
        "candidate_kind": "entity",
        "related_narratives": related_narratives,
        "focus_narrative": narrative_name,
    }


def write_json_if_changed(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    if path.exists():
        existing = path.read_text(encoding="utf-8")

        if existing == content:
            return False

    path.write_text(content, encoding="utf-8")
    return True


def build_tasks(
    wiki_root=DEFAULT_WIKI_ROOT,
    index_path=DEFAULT_INDEX_PATH,
    narrative_summary_path=DEFAULT_NARRATIVE_SUMMARY_PATH,
    target_date="",
    max_tasks=DEFAULT_MAX_TASKS,
):
    wiki_root = Path(wiki_root)
    index_path = Path(index_path)
    narrative_summary_path = Path(narrative_summary_path)

    daily_dir = wiki_root / "synthesis" / "daily"
    weekly_dir = wiki_root / "synthesis" / "weekly"
    tasks_dir = wiki_root / "tasks"

    index_records = load_jsonl(index_path)
    target_date_value = discover_target_date(daily_dir, index_records, target_date)
    target_date_text = target_date_value.isoformat()
    target_week = iso_week_key(target_date_value)

    daily_path = daily_dir / f"{target_date_text}.md"
    weekly_path = weekly_dir / f"{target_week}.md"
    daily_markdown = load_markdown_text(daily_path)
    weekly_markdown = load_markdown_text(weekly_path)

    summary, narrative_map, entity_map = load_summary_maps(narrative_summary_path)
    _ = summary
    narrative_records, entity_records = build_index_maps(index_records)

    markdown_narratives, markdown_entities = collect_markdown_focus(daily_markdown, weekly_markdown)
    target_scope_records = []

    for record in index_records:
        partition_date = parse_iso_date(record.get("partition_date"))

        if partition_date is None:
            timestamp = parse_iso_datetime(record.get("timestamp"))
            partition_date = timestamp.date() if timestamp is not None else None

        if partition_date == target_date_value:
            target_scope_records.append(record)

    narrative_focus = unique_text_list(
        markdown_narratives
        + select_top_narratives_from_records(
            target_scope_records,
            narrative_map,
            limit=5,
        )
    )

    if not narrative_focus:
        narrative_focus = unique_text_list(
            [name for name in narrative_map.keys()]
        )

    entity_focus = unique_text_list(
        markdown_entities
        + select_top_entities_from_records(
            target_scope_records,
            entity_map,
            limit=5,
        )
    )

    if not entity_focus:
        entity_focus = unique_text_list([name for name in entity_map.keys()])

    created_at = f"{target_date_text}T00:00:00+00:00"
    candidates = []

    for narrative_name in narrative_focus:
        if narrative_name not in narrative_map and narrative_name not in narrative_records:
            continue

        candidates.append(
            build_narrative_candidate(
                narrative_name,
                narrative_map,
                narrative_records,
                entity_map,
                daily_path,
                weekly_path,
                created_at,
            )
        )

    for entity_name in entity_focus:
        if entity_name not in entity_map and entity_name not in entity_records:
            continue

        candidates.append(
            build_entity_candidate(
                entity_name,
                entity_map,
                entity_records,
                narrative_map,
                daily_path,
                weekly_path,
                created_at,
            )
        )

    merged_candidates = dedupe_candidates(candidates)
    tasks = [finalize_task(candidate) for candidate in merged_candidates]
    tasks = sorted(
        tasks,
        key=lambda task: (
            -safe_int(task.get("priority"), 0),
            normalize_text(task.get("category")).lower(),
            normalize_text(task.get("narrative")).lower(),
            normalize_text(task.get("task_id")).lower(),
        ),
    )[: max_tasks or DEFAULT_MAX_TASKS]

    output_path = tasks_dir / f"{target_date_text}.json"
    output_written = write_json_if_changed(output_path, tasks)

    return {
        "target_date": target_date_text,
        "target_week": target_week,
        "index_record_count": len(index_records),
        "task_count": len(tasks),
        "output_path": output_path,
        "output_written": output_written,
        "tasks": tasks,
        "daily_synthesis_path": daily_path,
        "weekly_synthesis_path": weekly_path,
    }


def main():
    parser = argparse.ArgumentParser(description="Build deterministic Hermes tasks for Midas/OpenClaw.")
    parser.add_argument(
        "--wiki-root",
        default=str(DEFAULT_WIKI_ROOT),
        help="Hermes wiki root that contains synthesis memos and task artifacts.",
    )
    parser.add_argument(
        "--index-path",
        default=str(DEFAULT_INDEX_PATH),
        help="Path to workspace/wiki/meta/aeon_index.jsonl.",
    )
    parser.add_argument(
        "--narrative-summary-path",
        default=str(DEFAULT_NARRATIVE_SUMMARY_PATH),
        help="Path to narrative_summary.json used for deterministic task generation.",
    )
    parser.add_argument(
        "--target-date",
        default="",
        help="Target synthesis date. Defaults to the latest available daily synthesis memo.",
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=DEFAULT_MAX_TASKS,
        help="Maximum number of tasks to emit.",
    )

    args = parser.parse_args()

    result = build_tasks(
        wiki_root=Path(args.wiki_root),
        index_path=Path(args.index_path),
        narrative_summary_path=Path(args.narrative_summary_path),
        target_date=args.target_date,
        max_tasks=args.max_tasks,
    )

    print(f"Generated {result['task_count']} tasks for {result['target_date']}.")


if __name__ == "__main__":
    main()
