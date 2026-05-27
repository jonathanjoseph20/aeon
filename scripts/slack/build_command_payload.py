import argparse
import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
HERMES_DIR = REPO_ROOT / "scripts" / "hermes"

for path in (REPO_ROOT, HERMES_DIR):
    path_str = str(path)

    if path_str not in sys.path:
        sys.path.append(path_str)

from build_tasks import load_json, load_jsonl, normalize_text, safe_float, safe_int, unique_text_list, write_json_if_changed


DEFAULT_DIGEST_DIR = REPO_ROOT / "data" / "outbox" / "slack" / "daily-intel-digest"
DEFAULT_TASKS_DIR = REPO_ROOT / "workspace" / "wiki" / "tasks"
DEFAULT_SYNTHESIS_DIR = REPO_ROOT / "workspace" / "wiki" / "synthesis" / "daily"
DEFAULT_MIDAS_OUTBOX_DIR = REPO_ROOT / "data" / "outbox" / "midas" / "tasks"
DEFAULT_OUTBOX_DIR = REPO_ROOT / "data" / "outbox" / "slack" / "command-center"

SECTION_PREFIX = "## "
TOP_NARRATIVES_SECTION = "Top Narratives"
MAX_TOP_NARRATIVES = 5
MAX_TOP_TASKS = 5
MAX_PENDING_EXPORTS = 5


def clean_text(value):
    text = str(value or "")
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def truncate_text(value, limit):
    text = clean_text(value)

    if len(text) <= limit:
        return text

    if limit <= 1:
        return text[:limit]

    return text[: limit - 1].rstrip() + "…"


def parse_iso_date(value):
    text = normalize_text(value)

    if not text:
        return None

    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def discover_target_date(*directories, target_date=""):
    parsed = parse_iso_date(target_date)

    if parsed is not None:
        return parsed.isoformat()

    candidate_dates = []

    for directory in directories:
        directory = Path(directory)

        if not directory.exists():
            continue

        for path in directory.glob("*"):
            parsed = parse_iso_date(path.stem)

            if parsed is not None:
                candidate_dates.append(parsed)

    if candidate_dates:
        return max(candidate_dates).isoformat()

    return datetime.now(UTC).date().isoformat()


def load_json_list(path):
    payload = load_json(path)

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict) and isinstance(payload.get("tasks"), list):
        return payload["tasks"]

    return []


def parse_markdown_sections(body):
    sections = {}
    current_section = ""
    current_lines = []

    for raw_line in body.splitlines():
        line = raw_line.rstrip()

        if line.startswith(SECTION_PREFIX):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()

            current_section = line[len(SECTION_PREFIX) :].strip()
            current_lines = []
            continue

        if current_section:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


def parse_top_narrative_line(line):
    if not line.startswith("- "):
        return None

    parts = [part.strip() for part in line[2:].split(" | ")]

    if len(parts) < 6:
        return None

    narrative = parts[0].strip("`")
    priority = parts[1].removeprefix("priority ").strip("`")
    confidence = parts[2].removeprefix("confidence ").strip("`")
    sources = parts[3].removeprefix("sources ").strip("`")
    entities = parts[4].removeprefix("entities ").strip("`")
    records = parts[5].removeprefix("records ").strip("`")

    return {
        "narrative": clean_text(narrative),
        "priority": safe_float(priority, 0.0),
        "confidence": safe_int(confidence, 0),
        "source_count": safe_int(sources, 0),
        "entities": unique_text_list([entity.strip() for entity in clean_text(entities).split(",") if entity.strip()]),
        "record_count": safe_int(records, 0),
    }


def load_top_narratives(synthesis_path):
    synthesis_path = Path(synthesis_path)

    if not synthesis_path.exists():
        return []

    sections = parse_markdown_sections(synthesis_path.read_text(encoding="utf-8"))
    section_body = sections.get(TOP_NARRATIVES_SECTION, "")
    narratives = []

    for raw_line in section_body.splitlines():
        parsed = parse_top_narrative_line(raw_line.strip())

        if parsed:
            narratives.append(parsed)

    return narratives


def load_tasks(tasks_path):
    tasks = load_json_list(tasks_path)
    normalized = []

    for task in tasks:
        if not isinstance(task, dict):
            continue

        task = dict(task)
        task_date = normalize_text(task.get("task_date") or Path(tasks_path).stem)[:10] or Path(tasks_path).stem
        task_id = normalize_text(task.get("task_id"))
        task_key = normalize_text(task.get("task_key") or f"{task_date}:{task_id}")
        execution_state = normalize_text(task.get("execution_state") or task.get("state") or task.get("status")).lower()

        if execution_state not in {"pending", "acknowledged", "in_progress", "completed", "failed", "ignored"}:
            execution_state = "pending"

        task.update(
            {
                "task_date": task_date,
                "task_id": task_id,
                "task_key": task_key,
                "execution_state": execution_state,
                "status": normalize_text(task.get("status") or ("closed" if execution_state in {"completed", "failed", "ignored"} else "open")) or ("closed" if execution_state in {"completed", "failed", "ignored"} else "open"),
            }
        )
        normalized.append(task)

    return normalized


def sort_tasks(tasks):
    return sorted(
        tasks,
        key=lambda task: (
            normalize_text(task.get("execution_state")) in {"ignored", "completed", "failed"},
            -safe_float(task.get("priority"), 0.0),
            -safe_int(task.get("source_count"), 0),
            -safe_int(task.get("promotion_count"), 0),
            -safe_int(task.get("confidence"), 0),
            normalize_text(task.get("task_key")).lower(),
        ),
    )


def build_task_actions(task):
    execution_state = normalize_text(task.get("execution_state")).lower()
    actions = []

    if execution_state in {"pending", "acknowledged"}:
        actions.extend(["approve", "monitor", "escalate", "ignore"])

    if execution_state not in {"completed", "failed", "ignored"}:
        actions.append("send_to_midas")

    deduped = []
    seen = set()

    for action in actions:
        if action in seen:
            continue

        seen.add(action)
        deduped.append(action)

    return deduped


def build_task_summary(task):
    return {
        "task_id": normalize_text(task.get("task_id")),
        "task_key": normalize_text(task.get("task_key")),
        "narrative": normalize_text(task.get("narrative")),
        "category": normalize_text(task.get("category")),
        "priority": safe_float(task.get("priority"), 0.0),
        "confidence": safe_int(task.get("confidence"), 0),
        "source_count": safe_int(task.get("source_count"), 0),
        "promotion_count": safe_int(task.get("promotion_count"), 0),
        "execution_state": normalize_text(task.get("execution_state")).lower() or "pending",
        "status": normalize_text(task.get("status")) or "open",
        "midas_export_state": normalize_text(task.get("midas_export_state")),
        "suggested_actions": build_task_actions(task),
    }


def build_pending_export_summary(record):
    return {
        "task_id": normalize_text(record.get("task_id")),
        "task_key": normalize_text(record.get("task_key") or record.get("queue_key")),
        "narrative": normalize_text(record.get("narrative")),
        "category": normalize_text(record.get("category")),
        "execution_state": normalize_text(record.get("execution_state") or record.get("state")).lower() or "pending",
        "queue_position": safe_int(record.get("queue_position"), 0),
        "queue_state": normalize_text(record.get("queue_state")),
        "is_terminal": bool(record.get("is_terminal")),
    }


def build_text_summary(date_value, digest_payload, narratives, tasks, pending_exports):
    parts = [
        f"Slack Command Center ({date_value})",
        f"{len(narratives)} top narratives",
        f"{safe_int(digest_payload.get('promoted_to_hermes_count'), 0)} Hermes promotions",
        f"{len(tasks)} top tasks",
        f"{len(pending_exports)} pending Midas exports",
    ]

    if narratives:
        parts.append(
            "Top narrative: "
            + ", ".join(
                truncate_text(narrative["narrative"], 50)
                for narrative in narratives[:2]
            )
        )

    return " | ".join(parts)


def build_command_payload(
    digest_dir=DEFAULT_DIGEST_DIR,
    tasks_dir=DEFAULT_TASKS_DIR,
    synthesis_dir=DEFAULT_SYNTHESIS_DIR,
    midas_outbox_dir=DEFAULT_MIDAS_OUTBOX_DIR,
    outbox_dir=DEFAULT_OUTBOX_DIR,
    target_date="",
    write_output=True,
):
    digest_dir = Path(digest_dir)
    tasks_dir = Path(tasks_dir)
    synthesis_dir = Path(synthesis_dir)
    midas_outbox_dir = Path(midas_outbox_dir)
    outbox_dir = Path(outbox_dir)

    date_value = discover_target_date(digest_dir, tasks_dir, synthesis_dir, midas_outbox_dir, target_date=target_date)
    digest_path = digest_dir / f"{date_value}.json"
    tasks_path = tasks_dir / f"{date_value}.json"
    synthesis_path = synthesis_dir / f"{date_value}.md"
    midas_outbox_path = midas_outbox_dir / f"{date_value}.jsonl"
    output_path = outbox_dir / f"{date_value}.json"

    digest_payload = load_json(digest_path) or {}
    if not isinstance(digest_payload, dict):
        digest_payload = {}

    narratives = load_top_narratives(synthesis_path)[:MAX_TOP_NARRATIVES]
    tasks = sort_tasks(load_tasks(tasks_path))
    top_tasks = [
        build_task_summary(task)
        for task in tasks
        if normalize_text(task.get("execution_state")).lower() not in {"completed", "failed", "ignored"}
    ][:MAX_TOP_TASKS]
    pending_exports = [build_pending_export_summary(record) for record in load_jsonl(midas_outbox_path)][:MAX_PENDING_EXPORTS]

    payload = {
        "date": date_value,
        "title": "Slack Command Center",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_paths": {
            "daily_intel_digest": str(digest_path),
            "task_queue": str(tasks_path),
            "synthesis": str(synthesis_path),
            "midas_outbox": str(midas_outbox_path),
        },
        "hermes_promotions_count": safe_int(digest_payload.get("promoted_to_hermes_count"), 0),
        "top_narratives": narratives,
        "top_tasks": top_tasks,
        "pending_midas_exports": pending_exports,
        "suggested_actions": [
            {
                "action": action,
                "target_type": "task",
                "description": description,
            }
            for action, description in (
                ("approve", "Approve a task so it moves from pending into acknowledged state."),
                ("ignore", "Ignore a task or narrative so it closes out cleanly."),
                ("monitor", "Keep a task on watch without routing it outward yet."),
                ("escalate", "Escalate a task when it needs manual attention."),
                ("send_to_midas", "Mark a task export-ready for Midas routing."),
            )
        ],
    }
    payload["text"] = build_text_summary(date_value, digest_payload, narratives, top_tasks, pending_exports)

    if write_output:
        write_json_if_changed(output_path, payload)

    return {
        "date": date_value,
        "payload": payload,
        "output_path": output_path,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Slack command-center payload.")
    parser.add_argument(
        "--digest-dir",
        default=str(DEFAULT_DIGEST_DIR),
        help="Directory that contains data/outbox/slack/daily-intel-digest/YYYY-MM-DD.json.",
    )
    parser.add_argument(
        "--tasks-dir",
        default=str(DEFAULT_TASKS_DIR),
        help="Directory that contains workspace/wiki/tasks/YYYY-MM-DD.json.",
    )
    parser.add_argument(
        "--synthesis-dir",
        default=str(DEFAULT_SYNTHESIS_DIR),
        help="Directory that contains workspace/wiki/synthesis/daily/YYYY-MM-DD.md.",
    )
    parser.add_argument(
        "--midas-outbox-dir",
        default=str(DEFAULT_MIDAS_OUTBOX_DIR),
        help="Directory that contains data/outbox/midas/tasks/YYYY-MM-DD.jsonl.",
    )
    parser.add_argument(
        "--outbox-dir",
        default=str(DEFAULT_OUTBOX_DIR),
        help="Directory that receives data/outbox/slack/command-center/YYYY-MM-DD.json.",
    )
    parser.add_argument(
        "--date",
        default="",
        help="Explicit YYYY-MM-DD run date. Defaults to the newest available date across inputs.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Print the payload without writing the outbox artifact.",
    )

    args = parser.parse_args(argv)

    result = build_command_payload(
        digest_dir=Path(args.digest_dir),
        tasks_dir=Path(args.tasks_dir),
        synthesis_dir=Path(args.synthesis_dir),
        midas_outbox_dir=Path(args.midas_outbox_dir),
        outbox_dir=Path(args.outbox_dir),
        target_date=args.date,
        write_output=not args.preview,
    )

    if args.preview:
        print(json.dumps(result["payload"], indent=2, sort_keys=True))
    else:
        print(f"Wrote Slack command-center payload to {result['output_path']}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
