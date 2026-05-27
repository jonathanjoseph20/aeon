import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_TASKS_PATH = REPO_ROOT / "scripts" / "hermes" / "build_tasks.py"
EXPORT_TASKS_PATH = REPO_ROOT / "scripts" / "hermes" / "export_tasks.py"
IMPORT_TASK_UPDATES_PATH = REPO_ROOT / "scripts" / "hermes" / "import_task_updates.py"


def load_module(module_name, module_path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


build_tasks = load_module("build_tasks_coordination", BUILD_TASKS_PATH)
export_tasks = load_module("export_tasks_coordination", EXPORT_TASKS_PATH)
import_task_updates = load_module("import_task_updates_coordination", IMPORT_TASK_UPDATES_PATH)


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path, title, narrative_lines, entity_lines):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# Hermes Synthesis Memo", "", "## Executive Summary", f"- Scope: `{title}`."]

    if narrative_lines:
        lines.extend(["", "## Top Narratives", *narrative_lines])

    if entity_lines:
        lines.extend(["", "## Portfolio / Watchlist Relevance", *entity_lines])

    lines.extend(["", "## Suggested Follow-ups for Midas", *narrative_lines[:1], ""])

    path.write_text("\n".join(lines), encoding="utf-8")


class TaskCoordinationTests(unittest.TestCase):
    def write_fixture(self, temp_dir):
        temp_dir = Path(temp_dir)
        wiki_root = temp_dir / "workspace" / "wiki"
        index_path = wiki_root / "meta" / "aeon_index.jsonl"
        narrative_summary_path = temp_dir / "data" / "processed" / "narrative_summary.json"

        records = [
            {
                "memory_id": "openrouter-001",
                "title": "OpenRouter expansion check",
                "source": "Alpha Research (newsletter)",
                "timestamp": "2026-05-25T10:00:00+00:00",
                "source_url": "https://example.com/openrouter-1",
                "canonical_entities": ["OpenRouter", "AI"],
                "verticals": ["AI", "Portfolio"],
                "promotion_reasons": ["source_priority=high"],
                "confidence": 94,
                "narrative_membership": ["OpenRouter expansion"],
                "partition_date": "2026-05-25",
            },
            {
                "memory_id": "openrouter-002",
                "title": "OpenRouter expansion follow-up",
                "source": "Beta Research (twitter)",
                "timestamp": "2026-05-25T12:00:00+00:00",
                "source_url": "https://example.com/openrouter-2",
                "canonical_entities": ["OpenRouter", "AI"],
                "verticals": ["AI", "Portfolio"],
                "promotion_reasons": ["source_priority=high"],
                "confidence": 91,
                "narrative_membership": ["OpenRouter expansion"],
                "partition_date": "2026-05-25",
            },
            {
                "memory_id": "venice-001",
                "title": "Venice thesis update",
                "source": "Gamma Notes (pdf)",
                "timestamp": "2026-05-25T14:00:00+00:00",
                "source_url": "https://example.com/venice-1",
                "canonical_entities": ["Venice", "Dolphin"],
                "verticals": ["AI", "Portfolio"],
                "promotion_reasons": ["importance_score>=7"],
                "confidence": 97,
                "narrative_membership": ["Venice/Dolphin thesis"],
                "partition_date": "2026-05-25",
            },
            {
                "memory_id": "venice-002",
                "title": "Venice thesis reinforcement",
                "source": "Delta Brief (newsletter)",
                "timestamp": "2026-05-25T15:00:00+00:00",
                "source_url": "https://example.com/venice-2",
                "canonical_entities": ["Venice", "Dolphin"],
                "verticals": ["AI", "Portfolio"],
                "promotion_reasons": ["source_priority=high"],
                "confidence": 95,
                "narrative_membership": ["Venice/Dolphin thesis"],
                "partition_date": "2026-05-25",
            },
        ]

        write_jsonl(index_path, records)

        write_json(
            narrative_summary_path,
            {
                "generated_at": "2026-05-25T18:00:00+00:00",
                "entities": [
                    {
                        "canonical_name": "Venice",
                        "priority_score": 130.0,
                        "source_count": 4,
                        "promotion_count": 3,
                        "trend_status": "stable",
                        "verticals": ["AI", "Portfolio"],
                    },
                    {
                        "canonical_name": "OpenRouter",
                        "priority_score": 82.0,
                        "source_count": 3,
                        "promotion_count": 2,
                        "trend_status": "stable",
                        "verticals": ["AI", "Portfolio"],
                    },
                    {
                        "canonical_name": "Dolphin",
                        "priority_score": 64.0,
                        "source_count": 2,
                        "promotion_count": 1,
                        "trend_status": "stable",
                        "verticals": ["AI", "Portfolio"],
                    },
                ],
                "narratives": [
                    {
                        "narrative_name": "OpenRouter expansion",
                        "priority_score": 96.0,
                        "source_count": 3,
                        "mention_count": 5,
                        "promotion_count": 2,
                        "trend_status": "rising",
                        "canonical_entities": ["OpenRouter", "AI"],
                    },
                    {
                        "narrative_name": "Venice/Dolphin thesis",
                        "priority_score": 88.0,
                        "source_count": 2,
                        "mention_count": 4,
                        "promotion_count": 1,
                        "trend_status": "stable",
                        "canonical_entities": ["Venice", "Dolphin"],
                    },
                ],
                "top_narratives": [
                    {
                        "narrative_name": "OpenRouter expansion",
                        "priority_score": 96.0,
                    },
                    {
                        "narrative_name": "Venice/Dolphin thesis",
                        "priority_score": 88.0,
                    },
                ],
            },
        )

        write_markdown(
            wiki_root / "synthesis" / "daily" / "2026-05-25.md",
            "daily",
            [
                "- `OpenRouter expansion` | priority `96` | confidence `94` | sources `3` | entities `OpenRouter, AI` | records `3`",
                "- `Venice/Dolphin thesis` | priority `88` | confidence `95` | sources `2` | entities `Venice, Dolphin` | records `2`",
            ],
            [
                "- `Venice` | priority `130` | confidence `97` | sources `4` | narratives `Venice/Dolphin thesis` | records `2`",
                "- `OpenRouter` | priority `82` | confidence `94` | sources `3` | narratives `OpenRouter expansion` | records `2`",
            ],
        )
        write_markdown(
            wiki_root / "synthesis" / "weekly" / "2026-22.md",
            "weekly",
            [
                "- `OpenRouter expansion` | priority `96` | confidence `94` | sources `3` | entities `OpenRouter, AI` | records `3`",
            ],
            [
                "- `Venice` | priority `130` | confidence `97` | sources `4` | narratives `Venice/Dolphin thesis` | records `2`",
            ],
        )

        return wiki_root, index_path, narrative_summary_path

    def read_jsonl(self, path):
        return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_export_tasks_writes_queue_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wiki_root, _index_path, narrative_summary_path = self.write_fixture(temp_dir)
            build_tasks.build_tasks(
                wiki_root=wiki_root,
                index_path=wiki_root / "meta" / "aeon_index.jsonl",
                narrative_summary_path=narrative_summary_path,
                target_date="2026-05-25",
            )

            result = export_tasks.export_tasks(
                wiki_root=wiki_root,
                outbox_dir=Path(temp_dir) / "data" / "outbox" / "midas" / "tasks",
                target_date="2026-05-25",
            )
            second = export_tasks.export_tasks(
                wiki_root=wiki_root,
                outbox_dir=Path(temp_dir) / "data" / "outbox" / "midas" / "tasks",
                target_date="2026-05-25",
            )

            records = self.read_jsonl(result["outbox_path"])

            self.assertTrue(result["output_written"])
            self.assertFalse(second["output_written"])
            self.assertEqual(result["exported_count"], result["task_count"])
            self.assertEqual(len(records), result["task_count"])
            self.assertEqual(records[0]["execution_state"], "pending")
            self.assertEqual(records[0]["state"], "pending")
            self.assertIn("task_key", records[0])
            self.assertEqual(records, self.read_jsonl(second["outbox_path"]))

    def test_import_updates_merges_state_transitions_and_completion_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wiki_root, index_path, narrative_summary_path = self.write_fixture(temp_dir)
            build_result = build_tasks.build_tasks(
                wiki_root=wiki_root,
                index_path=index_path,
                narrative_summary_path=narrative_summary_path,
                target_date="2026-05-25",
            )

            tasks = build_result["tasks"]
            first_task = tasks[0]
            second_task = tasks[1]

            inbox_dir = Path(temp_dir) / "data" / "inbox" / "midas" / "task_updates"
            write_jsonl(
                inbox_dir / "2026-05-25.jsonl",
                [
                    {
                        "task_id": first_task["task_id"],
                        "task_key": first_task["task_key"],
                        "task_date": first_task["task_date"],
                        "state": "acknowledged",
                        "timestamp": "2026-05-25T09:00:00+00:00",
                        "source": "midas",
                        "note": "acknowledged",
                        "update_id": "update-ack-1",
                    },
                    {
                        "task_id": first_task["task_id"],
                        "task_key": first_task["task_key"],
                        "task_date": first_task["task_date"],
                        "state": "acknowledged",
                        "timestamp": "2026-05-25T09:00:00+00:00",
                        "source": "midas",
                        "note": "acknowledged",
                        "update_id": "update-ack-1",
                    },
                    {
                        "task_id": first_task["task_id"],
                        "task_key": first_task["task_key"],
                        "task_date": first_task["task_date"],
                        "state": "in_progress",
                        "timestamp": "2026-05-25T10:00:00+00:00",
                        "source": "midas",
                        "note": "in progress",
                        "update_id": "update-progress-1",
                    },
                    {
                        "task_id": first_task["task_id"],
                        "task_key": first_task["task_key"],
                        "task_date": first_task["task_date"],
                        "state": "completed",
                        "timestamp": "2026-05-25T11:00:00+00:00",
                        "source": "midas",
                        "note": "completed",
                        "update_id": "update-complete-1",
                    },
                    {
                        "task_id": first_task["task_id"],
                        "task_key": first_task["task_key"],
                        "task_date": first_task["task_date"],
                        "state": "completed",
                        "timestamp": "2026-05-25T11:00:00+00:00",
                        "source": "midas",
                        "note": "completed",
                        "update_id": "update-complete-1",
                    },
                    {
                        "task_id": second_task["task_id"],
                        "task_key": second_task["task_key"],
                        "task_date": second_task["task_date"],
                        "state": "ignored",
                        "timestamp": "2026-05-25T08:00:00+00:00",
                        "source": "midas",
                        "note": "ignored",
                        "update_id": "update-ignore-1",
                    },
                    {
                        "task_id": second_task["task_id"],
                        "task_key": second_task["task_key"],
                        "task_date": second_task["task_date"],
                        "state": "in_progress",
                        "timestamp": "2026-05-25T09:00:00+00:00",
                        "source": "midas",
                        "note": "late progress",
                        "update_id": "update-invalid-1",
                    },
                ],
            )

            result = import_task_updates.merge_updates(
                wiki_root=wiki_root,
                index_path=index_path,
                inbox_dir=inbox_dir,
            )
            second_pass = import_task_updates.merge_updates(
                wiki_root=wiki_root,
                index_path=index_path,
                inbox_dir=inbox_dir,
            )

            updated_tasks = json.loads(build_result["output_path"].read_text(encoding="utf-8"))
            first_updated = next(task for task in updated_tasks if task["task_key"] == first_task["task_key"])
            second_updated = next(task for task in updated_tasks if task["task_key"] == second_task["task_key"])
            index_records = self.read_jsonl(index_path)
            completion_records = [record for record in index_records if record.get("task_id") == first_task["task_id"]]

            self.assertEqual(result["applied_update_count"], 4)
            self.assertEqual(result["duplicate_update_count"], 2)
            self.assertEqual(result["invalid_update_count"], 1)
            self.assertEqual(first_updated["execution_state"], "completed")
            self.assertEqual(first_updated["status"], "closed")
            self.assertEqual(
                [entry["state"] for entry in first_updated["execution_history"]],
                ["pending", "acknowledged", "in_progress", "completed"],
            )
            self.assertTrue(first_updated["completion_memory_id"])
            self.assertEqual(second_updated["execution_state"], "ignored")
            self.assertEqual(second_updated["status"], "closed")
            self.assertEqual(
                [entry["state"] for entry in second_updated["execution_history"]],
                ["pending", "ignored"],
            )
            self.assertTrue(completion_records)
            self.assertEqual(completion_records[-1]["task_state"], "completed")
            self.assertEqual(completion_records[-1]["canonical_entities"], first_task["canonical_entities"])
            self.assertEqual(completion_records[-1]["narrative_membership"], [first_task["narrative"]])
            self.assertTrue(completion_records[-1]["synthesis_refs"])
            self.assertEqual(second_pass["task_file_writes"], 0)
            self.assertEqual(second_pass["index_writes"], 0)
            post_import_export = export_tasks.export_tasks(
                wiki_root=wiki_root,
                outbox_dir=Path(temp_dir) / "data" / "outbox" / "midas" / "tasks",
                target_date="2026-05-25",
            )
            self.assertEqual(post_import_export["exported_count"], build_result["task_count"] - 2)
            self.assertEqual(post_import_export["skipped_terminal_count"], 2)
            self.assertEqual(
                [entry["state"] for entry in first_updated["execution_history"]],
                [entry["state"] for entry in json.loads(build_result["output_path"].read_text(encoding="utf-8"))[0]["execution_history"]],
            )


if __name__ == "__main__":
    unittest.main()
