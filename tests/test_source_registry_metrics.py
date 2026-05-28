import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "build_source_metrics.py"
REGISTRY_PATH = REPO_ROOT / "config" / "source_registry.yml"


def load_module(module_name, module_path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


build_source_metrics = load_module("build_source_metrics", MODULE_PATH)


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


class SourceRegistryMetricsTests(unittest.TestCase):
    def test_canonical_registry_exposes_structural_fields(self):
        registry = build_source_metrics.load_source_registry(REGISTRY_PATH)

        self.assertGreaterEqual(len(registry), 1)

        for entry in registry:
            self.assertIn("source_id", entry)
            self.assertIn("platform", entry)
            self.assertIn("category", entry)
            self.assertIn("verticals", entry)
            self.assertIn("priority", entry)
            self.assertIn("trust_score", entry)
            self.assertIn("noise_score", entry)
            self.assertIn("enabled", entry)
            self.assertIn("tags", entry)
            self.assertIsInstance(entry["source_id"], str)
            self.assertIsInstance(entry["platform"], str)
            self.assertIsInstance(entry["category"], str)
            self.assertIsInstance(entry["verticals"], list)
            self.assertIsInstance(entry["priority"], str)
            self.assertIsInstance(entry["trust_score"], int)
            self.assertIsInstance(entry["noise_score"], int)
            self.assertIsInstance(entry["enabled"], bool)
            self.assertIsInstance(entry["tags"], list)
            self.assertGreater(len(entry["source_id"]), 0)
            self.assertGreaterEqual(entry["trust_score"], 0)
            self.assertLessEqual(entry["trust_score"], 100)
            self.assertGreaterEqual(entry["noise_score"], 0)
            self.assertLessEqual(entry["noise_score"], 100)

    def test_build_source_metrics_is_deterministic_and_tracks_yields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            registry_path = temp_dir / "config" / "source_registry.yml"
            intake_log_path = temp_dir / "data" / "processed" / "intake_log.jsonl"
            events_dir = temp_dir / "data" / "events" / "promote_to_hermes"
            hermes_dir = temp_dir / "data" / "hermes" / "promoted"
            output_path = temp_dir / "data" / "processed" / "source_metrics.json"

            registry_path.parent.mkdir(parents=True, exist_ok=True)
            registry_path.write_text(
                "\n".join(
                    [
                        "sources:",
                        "  - source_id: bankless",
                        "    platform: newsletter",
                        "    category: defi",
                        "    verticals: [DeFi, Macro]",
                        "    priority: high",
                        "    trust_score: 90",
                        "    noise_score: 10",
                        "    enabled: true",
                        "    tags: [newsletter, crypto]",
                        "",
                        "  - source_id: peter_attia",
                        "    platform: newsletter",
                        "    category: health",
                        "    verticals: [Personal, Health]",
                        "    priority: low",
                        "    trust_score: 95",
                        "    noise_score: 5",
                        "    enabled: true",
                        "    tags: [newsletter, longevity]",
                    ]
                ),
                encoding="utf-8",
            )

            write_jsonl(
                intake_log_path,
                [
                    {
                        "item_id": "bankless-001",
                        "timestamp": "2026-05-25T10:00:00+00:00",
                        "source_name": "Bankless",
                        "source_type": "newsletter",
                        "subject": "OpenAI and DeFi market structure",
                        "summary": "Bankless summary",
                        "content_preview": "Bankless preview",
                        "verticals": ["DeFi", "Macro"],
                        "entities": ["OpenAI"],
                    },
                    {
                        "item_id": "bankless-002",
                        "timestamp": "2026-05-25T10:05:00+00:00",
                        "source_name": "Bankless",
                        "source_type": "newsletter",
                        "subject": "OpenAI and DeFi market structure",
                        "summary": "Bankless summary",
                        "content_preview": "Bankless preview",
                        "verticals": ["DeFi", "Macro"],
                        "entities": ["OpenAI"],
                    },
                    {
                        "item_id": "bankless-003",
                        "timestamp": "2026-05-25T10:10:00+00:00",
                        "source_name": "Bankless",
                        "source_type": "newsletter",
                        "subject": "Base and OpenRouter activity",
                        "summary": "Another bankless summary",
                        "content_preview": "Another bankless preview",
                        "verticals": ["DeFi"],
                        "entities": ["Base", "OpenRouter"],
                    },
                    {
                        "item_id": "peter-001",
                        "timestamp": "2026-05-25T10:15:00+00:00",
                        "source_name": "Peter Attia",
                        "source_type": "newsletter",
                        "subject": "Longevity and recovery",
                        "summary": "Peter summary",
                        "content_preview": "Peter preview",
                        "verticals": ["Personal"],
                        "entities": ["Longevity"],
                    },
                    {
                        "item_id": "peter-002",
                        "timestamp": "2026-05-25T10:20:00+00:00",
                        "source_name": "Peter Attia",
                        "source_type": "newsletter",
                        "subject": "Sleep and supplements",
                        "summary": "Peter second summary",
                        "content_preview": "Peter second preview",
                        "verticals": [],
                        "entities": [],
                    },
                ],
            )

            write_jsonl(
                events_dir / "2026-05-25.jsonl",
                [
                    {
                        "promotion_hash": "promo-bankless-001",
                        "source_item_id": "bankless-001",
                        "source_name": "Bankless",
                    },
                ],
            )

            write_jsonl(
                hermes_dir / "2026-05-25.jsonl",
                [
                    {
                        "promotion_hash": "promo-bankless-001",
                        "source_item_id": "bankless-001",
                        "source_name": "Bankless",
                    },
                    {
                        "promotion_hash": "promo-bankless-003",
                        "source_item_id": "bankless-003",
                        "source_name": "Bankless",
                    },
                ],
            )

            first = build_source_metrics.compute_source_metrics(
                intake_log_path=intake_log_path,
                source_registry_path=registry_path,
                event_dir=events_dir,
                hermes_dir=hermes_dir,
                output_path=output_path,
            )

            first_payload = json.loads(output_path.read_text(encoding="utf-8"))
            second = build_source_metrics.compute_source_metrics(
                intake_log_path=intake_log_path,
                source_registry_path=registry_path,
                event_dir=events_dir,
                hermes_dir=hermes_dir,
                output_path=output_path,
            )

            second_payload = json.loads(output_path.read_text(encoding="utf-8"))

            self.assertEqual(first_payload, second_payload)
            self.assertEqual(first["source_count"], 2)
            self.assertEqual(first["item_count"], 5)
            self.assertEqual(len(first["source_metrics"]), 2)

            bankless = next(
                entry for entry in first_payload["sources"] if entry["source_id"] == "bankless"
            )
            peter = next(
                entry for entry in first_payload["sources"] if entry["source_id"] == "peter_attia"
            )

            self.assertEqual(bankless["item_count"], 3)
            self.assertEqual(bankless["promoted_count"], 2)
            self.assertEqual(bankless["duplicate_count"], 1)
            self.assertEqual(bankless["promotion_frequency"], 0.6667)
            self.assertEqual(bankless["promotion_hit_rate"], 1.0)
            self.assertEqual(bankless["entity_yield"], 1.0)
            self.assertEqual(bankless["theme_yield"], 1.0)
            self.assertEqual(bankless["duplicate_yield"], 0.3333)
            self.assertGreater(bankless["source_score"], peter["source_score"])

            self.assertEqual(peter["item_count"], 2)
            self.assertEqual(peter["promoted_count"], 0)
            self.assertEqual(peter["promotion_frequency"], 0.0)
            self.assertEqual(peter["promotion_hit_rate"], 0.0)
            self.assertEqual(peter["entity_yield"], 0.5)
            self.assertEqual(peter["theme_yield"], 0.5)
            self.assertEqual(peter["duplicate_yield"], 0.0)
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
