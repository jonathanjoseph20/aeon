import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLASSIFY_MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "classify_email.py"
PROMOTE_MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "promote_to_hermes.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_module(module_name, module_path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


classify_email = load_module("classify_email", CLASSIFY_MODULE_PATH)
promote_to_hermes = load_module("promote_to_hermes", PROMOTE_MODULE_PATH)


class SourceConfigScoringTests(unittest.TestCase):
    def test_source_priority_boosts_classification_score_and_vertical_priors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            sources_path = temp_dir / "config" / "sources.yml"
            sources_path.parent.mkdir(parents=True, exist_ok=True)
            sources_path.write_text(
                (FIXTURES_DIR / "source_priority_sources.yml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            raw_item = classify_email.parse_email_message(
                FIXTURES_DIR / "source_priority_email.txt"
            )
            source_entries = classify_email.load_source_entries(sources_path)

            record = classify_email.classify_item(
                raw_item,
                email_registry={},
                twitter_registry={},
                verticals={"DeFi": {"keywords": []}},
                watchlist={"entities": {}},
                seen=set(),
                source_entries=source_entries,
            )

            self.assertIsNotNone(record)
            self.assertEqual(record["source_name"], "Bankless")
            self.assertEqual(record["priority"], "high")
            self.assertEqual(record["importance_score"], 3)
            self.assertEqual(record["verticals"], ["DeFi"])
            self.assertTrue(record["digest_enabled"])
            self.assertTrue(record["alert_enabled"])

    def test_source_specific_promotion_threshold_overrides_global_threshold(self):
        fixture_log = FIXTURES_DIR / "promotion_threshold_override_intake_log.jsonl"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            events_dir = temp_dir / "events"
            hermes_dir = temp_dir / "hermes"

            result = promote_to_hermes.promote_items(
                input_log_path=fixture_log,
                event_dir=events_dir,
                hermes_dir=hermes_dir,
                run_date="2026-05-25",
                importance_threshold=7,
            )

            self.assertEqual(result["input_count"], 2)
            self.assertEqual(result["selected_count"], 0)
            self.assertEqual(result["event_writes"], 0)
            self.assertEqual(result["hermes_writes"], 0)
            self.assertEqual(result["suppressed_count"], 2)
            self.assertEqual(result["planned"], [])


if __name__ == "__main__":
    unittest.main()
