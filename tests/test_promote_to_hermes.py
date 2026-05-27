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


def write_jsonl(path, records):
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


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
            self.assertTrue(
                any(reason == "signal_band=High Signal" for reason in first_event["promotion_reasons"])
            )
            self.assertIn("source_priority=high", first_event["promotion_reasons"])

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

    def test_production_shape_regression_keeps_hermes_selective(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            events_dir = temp_dir / "events"
            hermes_dir = temp_dir / "hermes"
            input_log = temp_dir / "intake_log.jsonl"

            records = []

            for index in range(105):
                records.append(
                    {
                        "item_id": f"watchlist-only-{index:03d}",
                        "timestamp": f"2026-05-25T10:{index % 60:02d}:00+00:00",
                        "source_type": "twitter",
                        "source_name": f"Noise Feed {index:03d}",
                        "source_domain": "x.com",
                        "source_url": f"https://x.com/noise/status/{index}",
                        "subject": f"Watcher note {index:03d}",
                        "priority": "low",
                        "importance_score": 3,
                        "verticals": ["Macro"],
                        "watchlist_hits": [
                            {
                                "entity": "Base",
                                "matched_keywords": ["base"],
                                "score_boost": 4,
                            }
                        ],
                        "signal_band": "Normal Digest",
                        "summary": f"Generic note {index:03d}",
                        "content_preview": f"Generic note {index:03d}",
                    }
                )

            for index in range(24):
                records.append(
                    {
                        "item_id": f"generic-noise-{index:03d}",
                        "timestamp": f"2026-05-25T11:{index % 60:02d}:00+00:00",
                        "source_type": "newsletter",
                        "source_name": f"Market Wrap {index:03d}",
                        "source_domain": "market.example",
                        "source_url": f"mailto:market{index}@example.com",
                        "subject": f"Weekly stablecoin and tokenization wrap {index:03d}",
                        "priority": "low",
                        "importance_score": 5,
                        "verticals": ["RWA"],
                        "watchlist_hits": [],
                        "signal_band": "Normal Digest",
                        "summary": "Stablecoin and tokenization commentary",
                        "content_preview": "Stablecoin, RWA, tokenization, and private credit chatter.",
                    }
                )

            strong_entities = ["Venice", "Base", "OpenRouter"]
            source_types = ["email_manual", "newsletter", "pdf"]

            for index in range(12):
                entity = strong_entities[index % len(strong_entities)]
                source_type = source_types[index % len(source_types)]
                records.append(
                    {
                        "item_id": f"strong-{index:03d}",
                        "timestamp": f"2026-05-25T12:{index % 60:02d}:00+00:00",
                        "source_type": source_type,
                        "source_name": f"{entity} Desk {index % 4}",
                        "source_domain": f"{entity.lower()}.example",
                        "source_url": f"https://{entity.lower()}.example/{index}",
                        "subject": f"{entity} cross-source conviction update {index}",
                        "priority": "high",
                        "importance_score": 9,
                        "verticals": ["AI", "Portfolio"],
                        "watchlist_hits": [],
                        "signal_band": "High Signal",
                        "summary": f"{entity} is showing reinforcement across desks and sources.",
                        "content_preview": f"{entity} appears across multiple desks and source types.",
                    }
                )

            self.assertEqual(len(records), 141)
            write_jsonl(input_log, records)

            result = promote_to_hermes.promote_items(
                input_log_path=input_log,
                event_dir=events_dir,
                hermes_dir=hermes_dir,
                run_date="2026-05-25",
            )

            self.assertGreaterEqual(result["selected_count"], 5)
            self.assertLessEqual(result["selected_count"], 15)
            self.assertEqual(result["selected_count"], result["hermes_writes"])
            self.assertEqual(result["selected_count"], result["event_writes"])
            self.assertEqual(result["input_count"], 141)
            self.assertGreater(result["suppressed_count"], 100)

            planned_sources = {entry["event_record"]["source_name"] for entry in result["planned"]}
            self.assertTrue(any(source.startswith("Venice Desk") for source in planned_sources))
            self.assertTrue(any(source.startswith("Base Desk") for source in planned_sources))
            self.assertTrue(any(source.startswith("OpenRouter Desk") for source in planned_sources))
            self.assertFalse(
                any(
                    "watchlist-only" in entry["event_record"]["source_item_id"]
                    for entry in result["planned"]
                )
            )


if __name__ == "__main__":
    unittest.main()
