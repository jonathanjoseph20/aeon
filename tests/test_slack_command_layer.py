import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_MODULE_PATH = REPO_ROOT / "scripts" / "slack" / "build_command_payload.py"
UPDATES_MODULE_PATH = REPO_ROOT / "scripts" / "slack" / "apply_command_updates.py"


def load_module(module_name, module_path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


build_command_payload = load_module("build_command_payload", PAYLOAD_MODULE_PATH)
apply_command_updates = load_module("apply_command_updates", UPDATES_MODULE_PATH)


class SlackCommandLayerTests(unittest.TestCase):
    def write_json(self, path, payload):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def write_jsonl(self, path, records):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
            encoding="utf-8",
        )

    def write_fixture(self, temp_dir):
        temp_dir = Path(temp_dir)

        digest_dir = temp_dir / "data" / "outbox" / "slack" / "daily-intel-digest"
        tasks_dir = temp_dir / "workspace" / "wiki" / "tasks"
        synthesis_dir = temp_dir / "workspace" / "wiki" / "synthesis" / "daily"
        midas_outbox_dir = temp_dir / "data" / "outbox" / "midas" / "tasks"
        inbox_dir = temp_dir / "data" / "inbox" / "slack" / "commands"
        review_state_path = temp_dir / "data" / "outbox" / "slack" / "review-state.json"

        self.write_json(
            digest_dir / "2026-05-27.json",
            {
                "date": "2026-05-27",
                "promoted_to_hermes_count": 14,
                "title": "Daily Intelligence Digest",
            },
        )

        self.write_json(
            tasks_dir / "2026-05-27.json",
            [
                {
                    "task_id": "task-ai",
                    "task_key": "2026-05-27:task-ai",
                    "task_date": "2026-05-27",
                    "created_at": "2026-05-27T00:00:00+00:00",
                    "priority": 100,
                    "category": "thesis_update",
                    "narrative": "AI",
                    "canonical_entities": ["AI"],
                    "execution_state": "pending",
                    "status": "open",
                    "source_count": 44,
                    "promotion_count": 8,
                    "confidence": 99,
                    "suggested_action": "Approve AI thesis update.",
                },
                {
                    "task_id": "task-venice",
                    "task_key": "2026-05-27:task-venice",
                    "task_date": "2026-05-27",
                    "created_at": "2026-05-27T00:00:00+00:00",
                    "priority": 87,
                    "category": "thesis_update",
                    "narrative": "Venice",
                    "canonical_entities": ["Venice"],
                    "execution_state": "pending",
                    "status": "open",
                    "source_count": 14,
                    "promotion_count": 9,
                    "confidence": 97,
                    "suggested_action": "Review Venice thesis update.",
                },
                {
                    "task_id": "task-btc",
                    "task_key": "2026-05-27:task-btc",
                    "task_date": "2026-05-27",
                    "created_at": "2026-05-27T00:00:00+00:00",
                    "priority": 75,
                    "category": "opportunity",
                    "narrative": "BTC",
                    "canonical_entities": ["BTC"],
                    "execution_state": "pending",
                    "status": "open",
                    "source_count": 28,
                    "promotion_count": 0,
                    "confidence": 83,
                    "suggested_action": "Route BTC signal to Midas.",
                },
            ],
        )

        (synthesis_dir).mkdir(parents=True, exist_ok=True)
        (synthesis_dir / "2026-05-27.md").write_text(
            "\n".join(
                [
                    "# Hermes Synthesis Memo",
                    "",
                    "## Top Narratives",
                    "- `AI` | priority `100` | confidence `99` | sources `44` | entities `AI` | records `14`",
                    "- `Venice` | priority `87` | confidence `97` | sources `14` | entities `Venice` | records `2`",
                    "",
                    "## Portfolio / Watchlist Relevance",
                    "- `AI` | priority `324.5` | confidence `100` | sources `7` | narratives `AI` | records `9`",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        self.write_jsonl(
            midas_outbox_dir / "2026-05-27.jsonl",
            [
                {
                    "task_id": "task-ai",
                    "task_key": "2026-05-27:task-ai",
                    "narrative": "AI",
                    "category": "thesis_update",
                    "execution_state": "pending",
                    "queue_position": 1,
                    "queue_state": "pending",
                    "is_terminal": False,
                },
                {
                    "task_id": "task-venice",
                    "task_key": "2026-05-27:task-venice",
                    "narrative": "Venice",
                    "category": "thesis_update",
                    "execution_state": "pending",
                    "queue_position": 2,
                    "queue_state": "pending",
                    "is_terminal": False,
                },
            ],
        )

        return {
            "digest_dir": digest_dir,
            "tasks_dir": tasks_dir,
            "synthesis_dir": synthesis_dir,
            "midas_outbox_dir": midas_outbox_dir,
            "inbox_dir": inbox_dir,
            "review_state_path": review_state_path,
        }

    def read_tasks(self, tasks_path):
        return json.loads(Path(tasks_path).read_text(encoding="utf-8"))

    def write_commands(self, inbox_dir, records):
        self.write_jsonl(Path(inbox_dir) / "2026-05-27.jsonl", records)

    def test_payload_includes_top_narratives_and_pending_tasks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self.write_fixture(temp_dir)
            result = build_command_payload.build_command_payload(
                digest_dir=paths["digest_dir"],
                tasks_dir=paths["tasks_dir"],
                synthesis_dir=paths["synthesis_dir"],
                midas_outbox_dir=paths["midas_outbox_dir"],
                outbox_dir=Path(temp_dir) / "data" / "outbox" / "slack" / "command-center",
                target_date="2026-05-27",
            )

            payload = result["payload"]

            self.assertEqual(payload["date"], "2026-05-27")
            self.assertEqual(payload["hermes_promotions_count"], 14)
            self.assertEqual(payload["top_narratives"][0]["narrative"], "AI")
            self.assertEqual(payload["top_narratives"][1]["narrative"], "Venice")
            self.assertEqual(payload["top_tasks"][0]["task_key"], "2026-05-27:task-ai")
            self.assertIn("approve", payload["top_tasks"][0]["suggested_actions"])
            self.assertEqual(len(payload["pending_midas_exports"]), 2)
            self.assertEqual(payload["pending_midas_exports"][0]["task_key"], "2026-05-27:task-ai")

    def test_approve_task_changes_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self.write_fixture(temp_dir)
            self.write_commands(
                paths["inbox_dir"],
                [
                    {
                        "command_id": "cmd-approve-ai",
                        "timestamp": "2026-05-27T09:00:00+00:00",
                        "action": "approve",
                        "target_type": "task",
                        "target_id": "2026-05-27:task-ai",
                        "reason": "approved",
                        "actor": "user",
                    }
                ],
            )

            result = apply_command_updates.merge_command_updates(
                wiki_root=Path(temp_dir) / "workspace" / "wiki",
                inbox_dir=paths["inbox_dir"],
                review_state_path=paths["review_state_path"],
            )

            tasks = self.read_tasks(paths["tasks_dir"] / "2026-05-27.json")
            approved = next(task for task in tasks if task["task_key"] == "2026-05-27:task-ai")

            self.assertEqual(result["applied_count"], 1)
            self.assertEqual(approved["execution_state"], "acknowledged")
            self.assertEqual(approved["status"], "open")
            self.assertEqual(approved["execution_history"][-1]["state"], "acknowledged")

    def test_ignore_task_changes_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self.write_fixture(temp_dir)
            self.write_commands(
                paths["inbox_dir"],
                [
                    {
                        "command_id": "cmd-ignore-btc",
                        "timestamp": "2026-05-27T09:05:00+00:00",
                        "action": "ignore",
                        "target_type": "task",
                        "target_id": "2026-05-27:task-btc",
                        "reason": "not relevant",
                        "actor": "user",
                    }
                ],
            )

            result = apply_command_updates.merge_command_updates(
                wiki_root=Path(temp_dir) / "workspace" / "wiki",
                inbox_dir=paths["inbox_dir"],
                review_state_path=paths["review_state_path"],
            )

            tasks = self.read_tasks(paths["tasks_dir"] / "2026-05-27.json")
            ignored = next(task for task in tasks if task["task_key"] == "2026-05-27:task-btc")

            self.assertEqual(result["applied_count"], 1)
            self.assertEqual(ignored["execution_state"], "ignored")
            self.assertEqual(ignored["status"], "closed")
            self.assertEqual(ignored["execution_history"][-1]["state"], "ignored")

    def test_ignore_narrative_updates_review_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self.write_fixture(temp_dir)
            self.write_commands(
                paths["inbox_dir"],
                [
                    {
                        "command_id": "cmd-ignore-ai-narrative",
                        "timestamp": "2026-05-27T09:06:00+00:00",
                        "action": "ignore",
                        "target_type": "narrative",
                        "target_id": "AI",
                        "reason": "ignore narrative",
                        "actor": "user",
                    }
                ],
            )

            result = apply_command_updates.merge_command_updates(
                wiki_root=Path(temp_dir) / "workspace" / "wiki",
                inbox_dir=paths["inbox_dir"],
                review_state_path=paths["review_state_path"],
            )

            tasks = self.read_tasks(paths["tasks_dir"] / "2026-05-27.json")
            ignored = next(task for task in tasks if task["task_key"] == "2026-05-27:task-ai")
            review_state = json.loads(paths["review_state_path"].read_text(encoding="utf-8"))

            self.assertEqual(result["applied_count"], 1)
            self.assertEqual(ignored["execution_state"], "ignored")
            self.assertEqual(review_state["ignored_narratives"], ["AI"])

    def test_send_to_midas_marks_task_export_ready(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self.write_fixture(temp_dir)
            self.write_commands(
                paths["inbox_dir"],
                [
                    {
                        "command_id": "cmd-send-venice",
                        "timestamp": "2026-05-27T09:10:00+00:00",
                        "action": "send_to_midas",
                        "target_type": "task",
                        "target_id": "2026-05-27:task-venice",
                        "reason": "route",
                        "actor": "user",
                    }
                ],
            )

            result = apply_command_updates.merge_command_updates(
                wiki_root=Path(temp_dir) / "workspace" / "wiki",
                inbox_dir=paths["inbox_dir"],
                review_state_path=paths["review_state_path"],
            )

            tasks = self.read_tasks(paths["tasks_dir"] / "2026-05-27.json")
            routed = next(task for task in tasks if task["task_key"] == "2026-05-27:task-venice")

            self.assertEqual(result["applied_count"], 1)
            self.assertEqual(routed["midas_export_state"], "ready")
            self.assertEqual(routed["midas_export_requested_by"], "user")

    def test_rerun_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self.write_fixture(temp_dir)
            self.write_commands(
                paths["inbox_dir"],
                [
                    {
                        "command_id": "cmd-approve-ai",
                        "timestamp": "2026-05-27T09:00:00+00:00",
                        "action": "approve",
                        "target_type": "task",
                        "target_id": "2026-05-27:task-ai",
                        "reason": "approved",
                        "actor": "user",
                    }
                ],
            )

            first = apply_command_updates.merge_command_updates(
                wiki_root=Path(temp_dir) / "workspace" / "wiki",
                inbox_dir=paths["inbox_dir"],
                review_state_path=paths["review_state_path"],
            )
            first_tasks = self.read_tasks(paths["tasks_dir"] / "2026-05-27.json")

            second = apply_command_updates.merge_command_updates(
                wiki_root=Path(temp_dir) / "workspace" / "wiki",
                inbox_dir=paths["inbox_dir"],
                review_state_path=paths["review_state_path"],
            )
            second_tasks = self.read_tasks(paths["tasks_dir"] / "2026-05-27.json")

            self.assertEqual(first["applied_count"], 1)
            self.assertEqual(second["applied_count"], 0)
            self.assertEqual(second["duplicate_count"], 1)
            self.assertEqual(first_tasks, second_tasks)

    def test_invalid_commands_fail_safely(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self.write_fixture(temp_dir)
            self.write_commands(
                paths["inbox_dir"],
                [
                    {
                        "command_id": "cmd-invalid-action",
                        "timestamp": "2026-05-27T09:15:00+00:00",
                        "action": "launch",
                        "target_type": "task",
                        "target_id": "2026-05-27:task-ai",
                        "reason": "bad",
                        "actor": "user",
                    },
                    {
                        "timestamp": "2026-05-27T09:16:00+00:00",
                        "action": "ignore",
                        "target_type": "task",
                        "target_id": "2026-05-27:task-ai",
                        "reason": "missing command id",
                        "actor": "user",
                    },
                ],
            )

            result = apply_command_updates.merge_command_updates(
                wiki_root=Path(temp_dir) / "workspace" / "wiki",
                inbox_dir=paths["inbox_dir"],
                review_state_path=paths["review_state_path"],
            )

            tasks = self.read_tasks(paths["tasks_dir"] / "2026-05-27.json")

            self.assertEqual(result["applied_count"], 0)
            self.assertEqual(result["invalid_count"], 2)
            self.assertTrue(all(task["execution_state"] == "pending" for task in tasks))


if __name__ == "__main__":
    unittest.main()
