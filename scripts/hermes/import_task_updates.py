import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from build_tasks import (
    DEFAULT_INDEX_PATH,
    DEFAULT_WIKI_ROOT,
    TASK_TERMINAL_STATES,
    append_jsonl,
    build_completion_memory_record,
    build_execution_history_entry,
    build_task_completion_memory_id,
    load_json,
    load_jsonl,
    normalize_task_state,
    normalize_text,
    task_state_allows_transition,
    write_json_if_changed,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INBOX_DIR = REPO_ROOT / "data" / "inbox" / "midas" / "task_updates"


def canonical_update_payload(record):
    payload = {
        "task_id": normalize_text(record.get("task_id")),
        "task_key": normalize_text(
            record.get("task_key")
            or record.get("queue_id")
            or record.get("queue_key")
            or record.get("task_id")
        ),
        "task_date": normalize_text(record.get("task_date") or record.get("queue_date")),
        "state": normalize_task_state(record.get("state") or record.get("execution_state") or record.get("status")),
        "timestamp": normalize_text(
            record.get("timestamp")
            or record.get("updated_at")
            or record.get("completed_at")
            or record.get("created_at")
        ),
        "source": normalize_text(record.get("source") or record.get("actor") or "midas"),
        "note": normalize_text(record.get("note") or record.get("message") or record.get("summary")),
        "result": normalize_text(record.get("result") or record.get("output")),
        "evidence": record.get("evidence") if isinstance(record.get("evidence"), list) else [],
    }

    return payload


def update_fingerprint(payload):
    canonical = dict(payload)
    canonical.pop("update_id", None)
    canonical.pop("source_file", None)
    canonical.pop("line_number", None)
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"task-update-{digest}"


def normalize_update_record(record, source_file, line_number):
    payload = canonical_update_payload(record)
    update_id = normalize_text(record.get("update_id") or record.get("event_id") or record.get("id"))

    if not update_id:
        update_id = update_fingerprint(payload)

    payload.update(
        {
            "update_id": update_id,
            "source_file": str(source_file),
            "line_number": line_number,
        }
    )

    return payload


def load_updates(inbox_dir):
    inbox_dir = Path(inbox_dir)
    updates = []

    if not inbox_dir.exists():
        return updates

    for path in sorted(inbox_dir.glob("*.jsonl")):
        for line_number, record in enumerate(load_jsonl(path), start=1):
            updates.append(normalize_update_record(record, path, line_number))

    updates.sort(
        key=lambda item: (
            normalize_text(item.get("timestamp")),
            normalize_text(item.get("task_key")),
            normalize_text(item.get("update_id")),
            normalize_text(item.get("source_file")),
            int(item.get("line_number") or 0),
        )
    )
    return updates


def load_task_files(tasks_dir):
    tasks_dir = Path(tasks_dir)
    task_files = {}

    if not tasks_dir.exists():
        return task_files

    for path in sorted(tasks_dir.glob("*.json")):
        payload = load_json(path)

        if isinstance(payload, list):
            tasks = payload
        elif isinstance(payload, dict) and isinstance(payload.get("tasks"), list):
            tasks = payload["tasks"]
        else:
            tasks = []

        task_files[path] = tasks

    return task_files


def task_identity(task, task_file):
    task = dict(task)
    task_date = normalize_text(task.get("task_date") or task_file.stem)[:10] or task_file.stem
    task_id = normalize_text(task.get("task_id"))
    task_key = normalize_text(task.get("task_key") or f"{task_date}:{task_id}")
    task["task_date"] = task_date
    task["task_id"] = task_id
    task["task_key"] = task_key
    task.setdefault("execution_state", "pending")
    task.setdefault("execution_history", [])
    return task


def build_task_lookup(task_files):
    by_key = {}
    by_id = defaultdict(list)
    file_index = {}

    for path, tasks in task_files.items():
        normalized_tasks = []

        for index, task in enumerate(tasks):
            normalized = task_identity(task, path)
            normalized_tasks.append(normalized)
            lookup_entry = {
                "path": path,
                "index": index,
                "task": normalized,
            }

            key = normalize_text(normalized.get("task_key"))
            if key and key not in by_key:
                by_key[key] = lookup_entry

            task_id = normalize_text(normalized.get("task_id"))
            if task_id:
                by_id[task_id].append(lookup_entry)

        file_index[path] = normalized_tasks

    return by_key, by_id, file_index


def resolve_task_entry(update, by_key, by_id):
    task_key = normalize_text(update.get("task_key"))
    task_id = normalize_text(update.get("task_id"))
    task_date = normalize_text(update.get("task_date") or update.get("queue_date"))[:10]

    if task_key and task_key in by_key:
        return by_key[task_key]

    if task_id and task_date:
        compound_key = f"{task_date}:{task_id}"
        if compound_key in by_key:
            return by_key[compound_key]

    if task_id and len(by_id.get(task_id, [])) == 1:
        return by_id[task_id][0]

    if task_id and task_date:
        for entry in by_id.get(task_id, []):
            if normalize_text(entry["task"].get("task_date")) == task_date:
                return entry

    return None


def update_history_key(entry):
    return normalize_text(
        entry.get("update_id")
        or entry.get("state")
        or entry.get("timestamp")
        or entry.get("note")
    ).lower()


def completion_timestamp(task):
    for entry in task.get("execution_history", []) or []:
        if normalize_task_state(entry.get("state")) == "completed":
            return normalize_text(entry.get("timestamp") or entry.get("updated_at") or task.get("execution_state_updated_at"))

    return normalize_text(task.get("execution_state_updated_at"))


def apply_update_to_task(task, update):
    task = dict(task)
    task.setdefault("execution_history", [])
    task["execution_state"] = normalize_task_state(task.get("execution_state") or "pending")
    task["status"] = "closed" if task["execution_state"] in TASK_TERMINAL_STATES else "open"
    task["task_key"] = normalize_text(task.get("task_key") or f"{task.get('task_date')}:{task.get('task_id')}")
    task["task_date"] = normalize_text(task.get("task_date"))[:10] or normalize_text(task["task_key"]).split(":", 1)[0]

    history_seen = {update_history_key(entry) for entry in task.get("execution_history", [])}
    state = normalize_task_state(update.get("state"))
    timestamp = normalize_text(update.get("timestamp"))
    note = normalize_text(update.get("note") or update.get("result"))
    source = normalize_text(update.get("source") or "midas")
    update_id = normalize_text(update.get("update_id"))
    source_file = normalize_text(update.get("source_file"))
    line_number = int(update.get("line_number") or 0)
    state_changed = False

    if state == task["execution_state"]:
        return task, False, None, "duplicate"

    if update_id and update_id in history_seen:
        return task, False, None, "duplicate"

    if not task_state_allows_transition(task["execution_state"], state):
        return task, False, None, "invalid_transition"

    history_entry = build_execution_history_entry(
        task.get("task_key"),
        state,
        timestamp,
        source,
        note,
        update_id,
    )
    if source_file:
        history_entry["source_file"] = source_file
    if line_number:
        history_entry["line_number"] = line_number
    if update.get("result"):
        history_entry["result"] = normalize_text(update.get("result"))

    task["execution_history"].append(history_entry)
    task["execution_state"] = state
    task["execution_state_updated_at"] = timestamp or task.get("execution_state_updated_at")
    task["last_task_update_at"] = timestamp or task.get("last_task_update_at")
    task["last_task_update_source"] = source
    task["last_task_update_note"] = note
    task["last_task_update_id"] = update_id
    task["status"] = "closed" if state in TASK_TERMINAL_STATES else "open"
    state_changed = True

    if state == "completed":
        task["completion_memory_id"] = build_task_completion_memory_id(task.get("task_key"), timestamp)

    return task, state_changed, update, "applied"


def merge_updates(
    wiki_root=DEFAULT_WIKI_ROOT,
    index_path=DEFAULT_INDEX_PATH,
    inbox_dir=DEFAULT_INBOX_DIR,
):
    wiki_root = Path(wiki_root)
    index_path = Path(index_path)
    inbox_dir = Path(inbox_dir)
    tasks_dir = wiki_root / "tasks"

    task_files = load_task_files(tasks_dir)
    by_key, by_id, file_index = build_task_lookup(task_files)
    updates = load_updates(inbox_dir)
    existing_index_records = load_jsonl(index_path)
    existing_index_memory_ids = {
        normalize_text(record.get("memory_id"))
        for record in existing_index_records
        if normalize_text(record.get("memory_id"))
    }

    applied_updates = 0
    duplicate_updates = 0
    invalid_updates = 0
    unmatched_updates = 0
    updated_files = set()
    completion_records = []
    completed_tasks = {}

    for update in updates:
        entry = resolve_task_entry(update, by_key, by_id)

        if entry is None:
            unmatched_updates += 1
            continue

        task = entry["task"]
        updated_task, changed, applied_update, outcome = apply_update_to_task(task, update)
        entry["task"] = updated_task

        if outcome == "duplicate":
            duplicate_updates += 1
            continue

        if outcome == "invalid_transition":
            invalid_updates += 1
            continue

        if changed:
            applied_updates += 1
            file_index[entry["path"]][entry["index"]] = updated_task
            updated_files.add(entry["path"])
            by_key[normalize_text(updated_task.get("task_key"))] = entry
            task_id = normalize_text(updated_task.get("task_id"))
            if task_id:
                by_id[task_id] = [candidate for candidate in by_id.get(task_id, []) if candidate["path"] != entry["path"] or candidate["index"] != entry["index"]]
                by_id[task_id].append(entry)

            if updated_task.get("execution_state") == "completed":
                completed_tasks[normalize_text(updated_task.get("task_key"))] = updated_task

    for task_key, task in completed_tasks.items():
        completion_at = completion_timestamp(task)
        completion_memory_id = normalize_text(task.get("completion_memory_id"))

        if not completion_memory_id:
            completion_memory_id = build_task_completion_memory_id(task.get("task_key"), completion_at)
            task["completion_memory_id"] = completion_memory_id

        if completion_memory_id in existing_index_memory_ids:
            continue

        update_entry = next(
            (
                entry
                for entry in reversed(task.get("execution_history", []) or [])
                if normalize_task_state(entry.get("state")) == "completed"
            ),
            {},
        )
        completion_record = build_completion_memory_record(task, update_entry, completion_at)
        if normalize_text(completion_record.get("memory_id")) in existing_index_memory_ids:
            continue

        completion_records.append(completion_record)
        existing_index_memory_ids.add(normalize_text(completion_record.get("memory_id")))

    task_file_writes = 0

    for path in sorted(updated_files):
        if write_json_if_changed(path, file_index[path]):
            task_file_writes += 1

    index_writes = 0
    if completion_records:
        append_jsonl(index_path, completion_records)
        index_writes = len(completion_records)

    return {
        "input_update_count": len(updates),
        "applied_update_count": applied_updates,
        "duplicate_update_count": duplicate_updates,
        "invalid_update_count": invalid_updates,
        "unmatched_update_count": unmatched_updates,
        "task_file_writes": task_file_writes,
        "index_writes": index_writes,
        "completion_records": completion_records,
        "completion_record_count": len(completion_records),
        "updated_task_count": len(updated_files),
        "tasks_dir": tasks_dir,
        "index_path": index_path,
        "inbox_dir": inbox_dir,
    }


def main():
    parser = argparse.ArgumentParser(description="Merge deterministic Midas task updates back into Hermes state.")
    parser.add_argument(
        "--wiki-root",
        default=str(DEFAULT_WIKI_ROOT),
        help="Hermes wiki root that contains workspace/wiki/tasks/YYYY-MM-DD.json.",
    )
    parser.add_argument(
        "--index-path",
        default=str(DEFAULT_INDEX_PATH),
        help="Append-only aeon_index.jsonl path.",
    )
    parser.add_argument(
        "--inbox-dir",
        default=str(DEFAULT_INBOX_DIR),
        help="Directory that contains data/inbox/midas/task_updates/*.jsonl.",
    )

    args = parser.parse_args()

    result = merge_updates(
        wiki_root=Path(args.wiki_root),
        index_path=Path(args.index_path),
        inbox_dir=Path(args.inbox_dir),
    )

    print(
        "Merged {applied_update_count} updates ({completion_record_count} completions) from {input_update_count} records.".format(
            **result,
        )
    )


if __name__ == "__main__":
    main()
