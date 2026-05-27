import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
HERMES_DIR = REPO_ROOT / "scripts" / "hermes"

for path in (REPO_ROOT, HERMES_DIR):
    path_str = str(path)

    if path_str not in sys.path:
        sys.path.append(path_str)

from build_tasks import (
    TASK_TERMINAL_STATES,
    build_execution_history_entry,
    load_json,
    load_jsonl,
    normalize_task_state,
    normalize_text,
    task_state_allows_transition,
    unique_text_list,
    write_json_if_changed,
)


DEFAULT_WIKI_ROOT = REPO_ROOT / "workspace" / "wiki"
DEFAULT_INBOX_DIR = REPO_ROOT / "data" / "inbox" / "slack" / "commands"
DEFAULT_REVIEW_STATE_PATH = REPO_ROOT / "data" / "outbox" / "slack" / "review-state.json"

VALID_ACTIONS = {"approve", "ignore", "monitor", "escalate", "send_to_midas"}
VALID_TARGET_TYPES = {"task", "narrative", "entity"}


def load_task_file(path):
    payload = load_json(path)

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict) and isinstance(payload.get("tasks"), list):
        return payload["tasks"]

    return []


def normalize_task_record(task, task_file):
    task = dict(task)
    task_date = normalize_text(task.get("task_date") or task_file.stem)[:10] or task_file.stem
    task_id = normalize_text(task.get("task_id"))
    task_key = normalize_text(task.get("task_key") or f"{task_date}:{task_id}")
    execution_state = normalize_task_state(task.get("execution_state") or task.get("state") or task.get("status"))
    task["task_date"] = task_date
    task["task_id"] = task_id
    task["task_key"] = task_key
    task["execution_state"] = execution_state
    task["status"] = normalize_text(task.get("status") or ("closed" if execution_state in TASK_TERMINAL_STATES else "open")) or ("closed" if execution_state in TASK_TERMINAL_STATES else "open")
    task.setdefault("execution_history", [])
    task.setdefault("review_history", [])
    return task


def load_task_files(tasks_dir):
    tasks_dir = Path(tasks_dir)
    task_files = {}

    if not tasks_dir.exists():
        return task_files

    for path in sorted(tasks_dir.glob("*.json")):
        task_files[path] = [normalize_task_record(task, path) for task in load_task_file(path)]

    return task_files


def load_command_records(inbox_dir):
    inbox_dir = Path(inbox_dir)
    records = []

    if not inbox_dir.exists():
        return records

    for path in sorted(inbox_dir.glob("*.jsonl")):
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_line.strip():
                continue

            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            if not isinstance(record, dict):
                continue

            records.append(
                {
                    "command_id": normalize_text(record.get("command_id")),
                    "timestamp": normalize_text(record.get("timestamp")),
                    "action": normalize_text(record.get("action")).lower(),
                    "target_type": normalize_text(record.get("target_type")).lower(),
                    "target_id": normalize_text(record.get("target_id")),
                    "reason": normalize_text(record.get("reason")),
                    "actor": normalize_text(record.get("actor")),
                    "source_file": str(path),
                    "line_number": line_number,
                }
            )

    records.sort(
        key=lambda item: (
            normalize_text(item.get("timestamp")),
            normalize_text(item.get("command_id")),
            normalize_text(item.get("source_file")),
            int(item.get("line_number") or 0),
        )
    )
    return records


def load_review_state(path):
    payload = load_json(path) or {}

    if not isinstance(payload, dict):
        payload = {}

    return {
        "updated_at": normalize_text(payload.get("updated_at")),
        "applied_command_ids": unique_text_list(payload.get("applied_command_ids") or []),
        "ignored_narratives": unique_text_list(payload.get("ignored_narratives") or []),
        "ignored_entities": unique_text_list(payload.get("ignored_entities") or []),
        "manual_promotion_overrides": [
            entry
            for entry in (payload.get("manual_promotion_overrides") or [])
            if isinstance(entry, dict)
        ],
    }


def review_history_entry(command):
    return {
        "command_id": normalize_text(command.get("command_id")),
        "timestamp": normalize_text(command.get("timestamp")),
        "action": normalize_text(command.get("action")).lower(),
        "target_type": normalize_text(command.get("target_type")).lower(),
        "target_id": normalize_text(command.get("target_id")),
        "actor": normalize_text(command.get("actor")),
        "reason": normalize_text(command.get("reason")),
    }


def task_review_history_ids(task):
    ids = set()

    for entry in task.get("review_history", []) or []:
        command_id = normalize_text(entry.get("command_id"))

        if command_id:
            ids.add(command_id)

    for entry in task.get("execution_history", []) or []:
        update_id = normalize_text(entry.get("update_id"))

        if update_id:
            ids.add(update_id)

    return ids


def task_matches_target(task, target_type, target_id):
    if target_type == "task":
        return normalize_text(task.get("task_key")) == target_id or normalize_text(task.get("task_id")) == target_id

    if target_type == "narrative":
        return normalize_text(task.get("narrative")) == target_id

    if target_type == "entity":
        entities = [normalize_text(entity) for entity in task.get("canonical_entities") or []]
        return target_id in entities

    return False


def target_tasks_for_command(task_files, command):
    timestamp_date = normalize_text(command.get("timestamp"))[:10]
    file_path = None

    for path in task_files:
        if path.stem == timestamp_date:
            file_path = path
            break

    if file_path is None:
        return None, []

    target_type = normalize_text(command.get("target_type")).lower()
    target_id = normalize_text(command.get("target_id"))
    matches = [task for task in task_files[file_path] if task_matches_target(task, target_type, target_id)]
    return file_path, matches


def apply_command_to_task(task, command):
    task = dict(task)
    task.setdefault("review_history", [])
    task.setdefault("execution_history", [])
    command_id = normalize_text(command.get("command_id"))
    action = normalize_text(command.get("action")).lower()
    timestamp = normalize_text(command.get("timestamp"))
    current_state = normalize_task_state(task.get("execution_state"))

    if command_id in task_review_history_ids(task):
        return task, False, "duplicate"

    task["review_history"].append(review_history_entry(command))
    task["review_state"] = action
    task["reviewed_at"] = timestamp
    task["reviewed_by"] = normalize_text(command.get("actor"))
    task["review_reason"] = normalize_text(command.get("reason"))

    changed = False

    if action == "approve":
        if current_state in {"completed", "failed", "ignored"}:
            return task, False, "invalid_transition"

        if task_state_allows_transition(current_state, "acknowledged"):
            if current_state != "acknowledged":
                task["execution_state"] = "acknowledged"
                task["status"] = "open"
                task["execution_state_updated_at"] = timestamp or task.get("execution_state_updated_at")
                task.setdefault("execution_history", []).append(
                    build_execution_history_entry(
                        task.get("task_key"),
                        "acknowledged",
                        timestamp,
                        "slack",
                        normalize_text(command.get("reason")) or "Approved via Slack command.",
                        command_id,
                    )
                )
            changed = True
        else:
            return task, False, "invalid_transition"

    elif action == "ignore":
        if current_state in {"completed", "failed"}:
            return task, False, "invalid_transition"

        if current_state != "ignored":
            task["execution_state"] = "ignored"
            task["status"] = "closed"
            task["execution_state_updated_at"] = timestamp or task.get("execution_state_updated_at")
            task.setdefault("execution_history", []).append(
                build_execution_history_entry(
                    task.get("task_key"),
                    "ignored",
                    timestamp,
                    "slack",
                    normalize_text(command.get("reason")) or "Ignored via Slack command.",
                    command_id,
                )
            )
        changed = True

    elif action == "send_to_midas":
        if current_state in {"completed", "failed", "ignored"}:
            return task, False, "invalid_transition"

        if task.get("midas_export_state") != "ready":
            task["midas_export_state"] = "ready"
            task["midas_export_requested_at"] = timestamp
            task["midas_export_requested_by"] = normalize_text(command.get("actor"))
        changed = True

    elif action in {"monitor", "escalate"}:
        task["review_state"] = action
        task["reviewed_at"] = timestamp
        task["reviewed_by"] = normalize_text(command.get("actor"))
        task["review_reason"] = normalize_text(command.get("reason"))
        changed = True

    else:
        return task, False, "invalid_action"

    return task, changed, "applied"


def apply_command_to_review_state(review_state, command, target_tasks):
    command_id = normalize_text(command.get("command_id"))
    action = normalize_text(command.get("action")).lower()
    target_type = normalize_text(command.get("target_type")).lower()
    target_id = normalize_text(command.get("target_id"))
    timestamp = normalize_text(command.get("timestamp"))
    actor = normalize_text(command.get("actor"))
    reason = normalize_text(command.get("reason"))

    if command_id in review_state["applied_command_ids"]:
        return review_state, False

    review_state["applied_command_ids"].append(command_id)
    review_state["updated_at"] = timestamp

    if action == "ignore":
        if target_type == "narrative":
            review_state["ignored_narratives"] = unique_text_list(review_state["ignored_narratives"] + [target_id])
        elif target_type == "entity":
            review_state["ignored_entities"] = unique_text_list(review_state["ignored_entities"] + [target_id])

    if action in {"approve", "escalate", "send_to_midas"}:
        review_state["manual_promotion_overrides"].append(
            {
                "command_id": command_id,
                "timestamp": timestamp,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "actor": actor,
                "reason": reason,
                "matched_task_keys": unique_text_list([normalize_text(task.get("task_key")) for task in target_tasks]),
            }
        )

    return review_state, True


def merge_command_updates(
    wiki_root=DEFAULT_WIKI_ROOT,
    inbox_dir=DEFAULT_INBOX_DIR,
    review_state_path=DEFAULT_REVIEW_STATE_PATH,
):
    wiki_root = Path(wiki_root)
    inbox_dir = Path(inbox_dir)
    review_state_path = Path(review_state_path)
    tasks_dir = wiki_root / "tasks"

    task_files = load_task_files(tasks_dir)
    commands = load_command_records(inbox_dir)
    review_state = load_review_state(review_state_path)

    applied_count = 0
    duplicate_count = 0
    invalid_count = 0
    unmatched_count = 0
    updated_files = set()

    for command in commands:
        command_id = normalize_text(command.get("command_id"))
        timestamp = normalize_text(command.get("timestamp"))
        action = normalize_text(command.get("action")).lower()
        target_type = normalize_text(command.get("target_type")).lower()
        target_id = normalize_text(command.get("target_id"))
        actor = normalize_text(command.get("actor"))

        if not command_id or not timestamp or action not in VALID_ACTIONS or target_type not in VALID_TARGET_TYPES or not target_id or not actor:
            invalid_count += 1
            continue

        if command_id in review_state["applied_command_ids"]:
            duplicate_count += 1
            continue

        file_path, matches = target_tasks_for_command(task_files, command)

        if file_path is None or not matches:
            unmatched_count += 1
            continue

        updated_tasks = []
        action_failed = False
        any_changed = False

        for task in task_files[file_path]:
            if not task_matches_target(task, target_type, target_id):
                updated_tasks.append(task)
                continue

            updated_task, changed, outcome = apply_command_to_task(task, command)

            if outcome == "duplicate":
                duplicate_count += 1
                action_failed = True
                break

            if outcome != "applied":
                invalid_count += 1
                action_failed = True
                break

            updated_tasks.append(updated_task)
            any_changed = any_changed or changed

        if action_failed:
            continue

        if any_changed:
            task_files[file_path] = updated_tasks
            updated_files.add(file_path)
            review_state, _ = apply_command_to_review_state(review_state, command, matches)
            applied_count += 1

    task_file_writes = 0

    for path in sorted(updated_files):
        if write_json_if_changed(path, task_files[path]):
            task_file_writes += 1

    review_state_writes = 0
    if write_json_if_changed(review_state_path, review_state):
        review_state_writes = 1

    return {
        "input_count": len(commands),
        "applied_count": applied_count,
        "duplicate_count": duplicate_count,
        "invalid_count": invalid_count,
        "unmatched_count": unmatched_count,
        "task_file_writes": task_file_writes,
        "review_state_writes": review_state_writes,
        "tasks_dir": tasks_dir,
        "review_state_path": review_state_path,
        "inbox_dir": inbox_dir,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Apply deterministic Slack command updates to Hermes task state.")
    parser.add_argument(
        "--wiki-root",
        default=str(DEFAULT_WIKI_ROOT),
        help="Hermes wiki root that contains workspace/wiki/tasks/YYYY-MM-DD.json.",
    )
    parser.add_argument(
        "--inbox-dir",
        default=str(DEFAULT_INBOX_DIR),
        help="Directory that contains data/inbox/slack/commands/*.jsonl.",
    )
    parser.add_argument(
        "--review-state-path",
        default=str(DEFAULT_REVIEW_STATE_PATH),
        help="Append-only review state snapshot path under data/outbox/slack.",
    )

    args = parser.parse_args(argv)

    result = merge_command_updates(
        wiki_root=Path(args.wiki_root),
        inbox_dir=Path(args.inbox_dir),
        review_state_path=Path(args.review_state_path),
    )

    print(
        "Applied {applied_count} Slack commands from {input_count} records.".format(
            **result,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
