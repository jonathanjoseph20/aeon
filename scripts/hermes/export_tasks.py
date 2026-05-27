import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from build_tasks import (
    DEFAULT_WIKI_ROOT,
    TASK_TERMINAL_STATES,
    load_json,
    normalize_task_state,
    normalize_text,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTBOX_DIR = REPO_ROOT / "data" / "outbox" / "midas" / "tasks"


def load_task_list(path):
    payload = load_json(path)

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        tasks = payload.get("tasks")

        if isinstance(tasks, list):
            return tasks

    return []


def write_jsonl_if_changed(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(record, sort_keys=True) for record in records)

    if content:
        content += "\n"

    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False

    path.write_text(content, encoding="utf-8")
    return True


def discover_task_date(tasks_dir, target_date=""):
    target = normalize_text(target_date)

    if target:
        return target

    tasks_dir = Path(tasks_dir)
    candidate_dates = []

    if tasks_dir.exists():
        for path in tasks_dir.glob("*.json"):
            try:
                candidate_dates.append(date.fromisoformat(path.stem))
            except ValueError:
                continue

    if candidate_dates:
        return max(candidate_dates).isoformat()

    return date.today().isoformat()


def normalize_queue_record(task, task_path, queue_date, queue_position):
    task = dict(task)
    execution_state = normalize_task_state(task.get("execution_state") or task.get("state") or task.get("status"))
    task_date = normalize_text(task.get("task_date") or queue_date)[:10] or queue_date
    task_id = normalize_text(task.get("task_id"))
    task_key = normalize_text(task.get("task_key") or f"{task_date}:{task_id}")

    task["execution_state"] = execution_state
    task["state"] = execution_state
    task["queue_state"] = execution_state
    task["task_date"] = task_date
    task["task_key"] = task_key
    task["queue_date"] = queue_date
    task["queue_position"] = queue_position
    task["queue_id"] = f"{queue_date}:{queue_position:04d}:{task_key}"
    task["exported_at"] = f"{queue_date}T00:00:00+00:00"
    try:
        task["source_task_path"] = str(task_path.relative_to(REPO_ROOT))
    except ValueError:
        task["source_task_path"] = str(task_path)
    task["is_terminal"] = execution_state in TASK_TERMINAL_STATES

    return task


def export_tasks(
    wiki_root=DEFAULT_WIKI_ROOT,
    outbox_dir=DEFAULT_OUTBOX_DIR,
    target_date="",
):
    wiki_root = Path(wiki_root)
    tasks_dir = wiki_root / "tasks"
    queue_date = discover_task_date(tasks_dir, target_date)
    task_path = tasks_dir / f"{queue_date}.json"
    outbox_path = Path(outbox_dir) / f"{queue_date}.jsonl"

    tasks = load_task_list(task_path)
    exportable_tasks = []
    skipped_terminal = 0
    seen_keys = set()

    for index, task in enumerate(tasks, start=1):
        normalized = dict(task)
        execution_state = normalize_task_state(
            normalized.get("execution_state") or normalized.get("state") or normalized.get("status")
        )

        if execution_state in TASK_TERMINAL_STATES:
            skipped_terminal += 1
            continue

        queue_record = normalize_queue_record(normalized, task_path, queue_date, len(exportable_tasks) + 1)
        queue_key = normalize_text(queue_record.get("task_key") or queue_record.get("task_id"))

        if not queue_key or queue_key in seen_keys:
            continue

        seen_keys.add(queue_key)
        exportable_tasks.append(queue_record)

    output_written = write_jsonl_if_changed(outbox_path, exportable_tasks)

    return {
        "queue_date": queue_date,
        "task_input_path": task_path,
        "outbox_path": outbox_path,
        "task_count": len(tasks),
        "exported_count": len(exportable_tasks),
        "skipped_terminal_count": skipped_terminal,
        "output_written": output_written,
        "tasks": exportable_tasks,
    }


def main():
    parser = argparse.ArgumentParser(description="Export Hermes tasks into the deterministic Midas outbox.")
    parser.add_argument(
        "--wiki-root",
        default=str(DEFAULT_WIKI_ROOT),
        help="Hermes wiki root that contains workspace/wiki/tasks/YYYY-MM-DD.json.",
    )
    parser.add_argument(
        "--outbox-dir",
        default=str(DEFAULT_OUTBOX_DIR),
        help="Directory that receives data/outbox/midas/tasks/YYYY-MM-DD.jsonl.",
    )
    parser.add_argument(
        "--date",
        default="",
        help="Task queue date to export. Defaults to the newest task file in workspace/wiki/tasks.",
    )

    args = parser.parse_args()

    result = export_tasks(
        wiki_root=Path(args.wiki_root),
        outbox_dir=Path(args.outbox_dir),
        target_date=args.date,
    )

    print(
        "Exported {exported_count} tasks for {queue_date} to {outbox_path}.".format(
            **result,
        )
    )


if __name__ == "__main__":
    main()
