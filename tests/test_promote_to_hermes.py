import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "promote_to_hermes.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_promote_to_hermes_module():
    spec = importlib.util.spec_from_file_location(
        "promote_to_hermes",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


promote_to_hermes = load_promote_to_hermes_module()


def read_jsonl(path):
    if not path.exists():
        return []

    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


class PromoteToHermesTests(unittest.TestCase):
    def setUp(self):
        self.fixture_log = FIXTURES_DIR / "promote_to_hermes_intake_log.jsonl"

    def test_promotes_only_the_highest_conviction_item_and_materializes_append_only_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            events_dir = temp_dir / "events"
            hermes_dir = temp_dir / "hermes"

            result = promote_to_hermes.promote_items(
                input_log_path=self.fixture_log,
                event_dir=events_dir,
                hermes_dir=hermes_dir,
                run_date="2026-05-25",
                dry_run=False,
                include_slack_payloads=True,
            )

            self.assertEqual(result["input_count"], 5)
            self.assertEqual(result["selected_count"], 1)
            self.assertEqual(result["event_writes"], 1)
            self.assertEqual(result["hermes_writes"], 1)
            self.assertGreaterEqual(result["suppressed_count"], 3)

            event_records = read_jsonl(events_dir / "2026-05-25.jsonl")
            hermes_records = read_jsonl(hermes_dir / "2026-05-25.jsonl")

            self.assertEqual(len(event_records), 1)
            self.assertEqual(len(hermes_records), 1)

            first_event = event_records[0]
            self.assertEqual(first_event["event_type"], "promote_to_hermes")
            self.assertEqual(first_event["source_name"], "Alpha Research")
            self.assertEqual(first_event["source_type"], "email_manual")
            self.assertEqual(first_event["verticals"], ["AI", "Macro"])
            self.assertEqual(first_event["tags"], ["ai", "macro"])
            self.assertEqual(first_event["importance_score"], 9)
            self.assertEqual(first_event["dedupe_hash"], "alpha-hash-001")
            self.assertEqual(first_event["signal_band"], "High Signal")
            self.assertEqual(first_event["summary"], "Alpha summary for Hermes")
            self.assertEqual(first_event["preview"], "Alpha preview for Hermes")
            self.assertIn("slack_notification", first_event)
            self.assertGreaterEqual(first_event["promotion_reason_fields"]["signal_count"], 2)
            self.assertGreaterEqual(first_event["promotion_confidence"], 80)
            self.assertTrue(
                any(reason.startswith("importance_score>=") for reason in first_event["promotion_reasons"])
            )
            self.assertIn("source_priority=high", first_event["promotion_reasons"])
            self.assertTrue(
                any(reason.startswith("cross_source_entity=") for reason in first_event["promotion_reasons"])
            )

            promoted_hashes = {record["promotion_hash"] for record in event_records}
            self.assertEqual(len(promoted_hashes), 1)

    def test_second_run_is_replay_safe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            events_dir = temp_dir / "events"
            hermes_dir = temp_dir / "hermes"

            first = promote_to_hermes.promote_items(
                input_log_path=self.fixture_log,
                event_dir=events_dir,
                hermes_dir=hermes_dir,
                run_date="2026-05-25",
            )

            second = promote_to_hermes.promote_items(
                input_log_path=self.fixture_log,
                event_dir=events_dir,
                hermes_dir=hermes_dir,
                run_date="2026-05-25",
            )

            self.assertEqual(first["selected_count"], 1)
            self.assertEqual(second["selected_count"], 0)
            self.assertEqual(second["event_writes"], 0)
            self.assertEqual(second["hermes_writes"], 0)

            event_records = read_jsonl(events_dir / "2026-05-25.jsonl")
            hermes_records = read_jsonl(hermes_dir / "2026-05-25.jsonl")

            self.assertEqual(len(event_records), 1)
            self.assertEqual(len(hermes_records), 1)

    def test_dry_run_does_not_write_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            events_dir = temp_dir / "events"
            hermes_dir = temp_dir / "hermes"

            result = promote_to_hermes.promote_items(
                input_log_path=self.fixture_log,
                event_dir=events_dir,
                hermes_dir=hermes_dir,
                run_date="2026-05-25",
                dry_run=True,
            )

            self.assertEqual(result["selected_count"], 1)
            self.assertEqual(result["event_writes"], 1)
            self.assertEqual(result["hermes_writes"], 1)
            self.assertFalse((events_dir / "2026-05-25.jsonl").exists())
            self.assertFalse((hermes_dir / "2026-05-25.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
