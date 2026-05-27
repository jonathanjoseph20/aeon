import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLASSIFY_MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "classify_email.py"
BUILD_DIGEST_MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "build_digest.py"
PROMOTE_MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "promote_to_hermes.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_module(module_name, module_path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


classify_email = load_module("classify_email", CLASSIFY_MODULE_PATH)
build_digest = load_module("build_digest", BUILD_DIGEST_MODULE_PATH)
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

    def test_personal_health_newsletter_stays_out_of_defi_without_explicit_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            email_path = temp_dir / "peter_attia_health_note.txt"
            email_path.write_text(
                "\n".join(
                    [
                        "SOURCE: Peter Attia",
                        "SOURCE_DOMAIN: peterattiamd.com",
                        "KNOWN_SOURCE: False",
                        "SENDER: Peter Attia <news@peterattiamd.com>",
                        "SUBJECT: A guide to medications and supplements",
                        "PRIORITY: low",
                        "IMPORTANCE_SCORE: 1",
                        "GMAIL_LABEL: Research/DeFi",
                        "",
                        "A practical guide to medications, supplements, and personal health decisions.",
                    ]
                ),
                encoding="utf-8",
            )

            raw_item = classify_email.parse_email_message(email_path)
            record = classify_email.classify_item(
                raw_item,
                email_registry=classify_email.load_email_registry(),
                twitter_registry={},
                verticals=classify_email.load_verticals(),
                watchlist={"entities": {}},
                seen=set(),
                source_entries=[],
            )

            self.assertIsNotNone(record)
            self.assertIn("Personal", record["verticals"])
            self.assertNotIn("DeFi", record["verticals"])
            self.assertNotIn("RWA", record["verticals"])
            self.assertNotIn("AI", record["verticals"])
            self.assertEqual(record["scores"].get("DeFi", 0), 0)

    def test_personal_health_newsletter_can_still_surface_explicit_ai_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            email_path = temp_dir / "peter_attia_ai_note.txt"
            email_path.write_text(
                "\n".join(
                    [
                        "SOURCE: Peter Attia",
                        "SOURCE_DOMAIN: peterattiamd.com",
                        "KNOWN_SOURCE: False",
                        "SENDER: Peter Attia <news@peterattiamd.com>",
                        "SUBJECT: AI tools for health tracking",
                        "PRIORITY: low",
                        "IMPORTANCE_SCORE: 1",
                        "GMAIL_LABEL: Research/DeFi",
                        "",
                        "A practical look at open-source AI agents, model selection, and compute tradeoffs for health tracking.",
                    ]
                ),
                encoding="utf-8",
            )

            raw_item = classify_email.parse_email_message(email_path)
            record = classify_email.classify_item(
                raw_item,
                email_registry=classify_email.load_email_registry(),
                twitter_registry={},
                verticals=classify_email.load_verticals(),
                watchlist={"entities": {}},
                seen=set(),
                source_entries=[],
            )

            self.assertIsNotNone(record)
            self.assertIn("Personal", record["verticals"])
            self.assertIn("AI", record["verticals"])
            self.assertNotIn("DeFi", record["verticals"])

    def test_peter_attia_processed_rows_are_rebuilt_before_digesting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            log_path = temp_dir / "data" / "processed" / "intake_log.jsonl"
            digest_path = temp_dir / "data" / "processed" / "daily_digest.md"
            cluster_path = temp_dir / "data" / "processed" / "topic_clusters.jsonl"
            entity_summary_path = temp_dir / "data" / "processed" / "entity_summary.json"

            log_path.parent.mkdir(parents=True, exist_ok=True)

            stale_record = {
                "item_id": "312a9f9f258b8d00",
                "dedupe_hash": "312a9f9f258b8d00",
                "source_name": "Peter Attia",
                "subject": "A guide to medications and supplements: determining what to take, what to skip, and how to know if they're working for you",
                "verticals": ["DeFi", "Portfolio", "Personal", "Macro"],
                "importance_score": 7,
                "summary": "stale summary",
                "content_preview": "stale preview",
            }
            log_path.write_text(json.dumps(stale_record) + "\n", encoding="utf-8")

            raw_item = classify_email.parse_email_message(
                REPO_ROOT / "data" / "intake" / "email" / "gmail_19e5ecbb5e477f14.txt"
            )

            records = classify_email.classify_and_write_records(
                [raw_item],
                log_path,
                email_registry=classify_email.load_email_registry(),
                twitter_registry={},
                verticals=classify_email.load_verticals(),
                watchlist={"entities": {}},
                source_entries=[],
            )

            self.assertEqual(len(records), 1)

            rewritten_records = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(rewritten_records), 1)
            self.assertEqual(rewritten_records[0]["source_name"], "Peter Attia")
            self.assertIn("Personal", rewritten_records[0]["verticals"])
            self.assertNotIn("DeFi", rewritten_records[0]["verticals"])

            entity_summary_path.write_text(
                json.dumps(
                    {
                        "generated_at": "",
                        "entity_count": 0,
                        "entities": [],
                        "top_emerging_entities": [],
                        "most_mentioned_entities": [],
                        "cross_source_entities": [],
                    }
                ),
                encoding="utf-8",
            )

            build_digest.write_digest(
                log_path=log_path,
                cluster_path=cluster_path,
                entity_summary_path=entity_summary_path,
                digest_path=digest_path,
            )

            digest_text = digest_path.read_text(encoding="utf-8")
            self.assertIn("## Personal", digest_text)
            self.assertNotIn("## DeFi", digest_text)
            self.assertIn("Peter Attia", digest_text)

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
