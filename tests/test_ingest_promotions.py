import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "hermes" / "ingest_promotions.py"


def load_module(module_name, module_path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ingest_promotions = load_module("ingest_promotions", MODULE_PATH)


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def read_jsonl(path):
    path = Path(path)

    if not path.exists():
        return []

    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class HermesPromotionIngestionTests(unittest.TestCase):
    def build_record(self, *, title, canonical_entities, source_url, promotion_hash):
        return {
            "title": title,
            "source_name": "Alpha Research",
            "source_type": "newsletter",
            "timestamp": "2026-05-25T12:00:00Z",
            "source_url": source_url,
            "canonical_entities": canonical_entities,
            "verticals": ["AI", "Portfolio"],
            "promotion_reasons": ["importance_score>=7", "source_priority=high"],
            "promotion_confidence": 97,
            "narrative_membership": ["Venice/Dolphin thesis", "AI inference market"],
            "promotion_hash": promotion_hash,
        }

    def test_duplicate_suppression_handles_same_source_url_and_similar_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            promoted_path = temp_dir / "2026-05-25.jsonl"
            wiki_root = temp_dir / "workspace" / "wiki"
            index_path = wiki_root / "meta" / "aeon_index.jsonl"

            write_jsonl(
                promoted_path,
                [
                    self.build_record(
                        title="Venice thesis update",
                        canonical_entities=["Venice"],
                        source_url="https://example.com/venice",
                        promotion_hash="prom-001",
                    ),
                    self.build_record(
                        title="Venice thesis update refreshed",
                        canonical_entities=["Venice"],
                        source_url="https://example.com/venice",
                        promotion_hash="prom-002",
                    ),
                    self.build_record(
                        title="Venice thesis refreshed",
                        canonical_entities=["Venice"],
                        source_url="https://example.com/other-venice",
                        promotion_hash="prom-003",
                    ),
                ],
            )

            result = ingest_promotions.ingest_promotions(
                promoted_path=promoted_path,
                wiki_root=wiki_root,
                index_path=index_path,
                partition_date="2026-05-25",
            )

            self.assertEqual(result["input_count"], 3)
            self.assertEqual(result["selected_count"], 1)
            self.assertEqual(result["suppressed_count"], 2)

            wiki_files = sorted(wiki_root.glob("aeon/2026-05-25/*.md"))
            index_records = read_jsonl(index_path)

            self.assertEqual(len(wiki_files), 1)
            self.assertEqual(len(index_records), 1)
            self.assertTrue(wiki_files[0].name.startswith("venice--"))

    def test_filename_is_stable_across_reruns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            promoted_path = temp_dir / "2026-05-25.jsonl"
            wiki_root = temp_dir / "workspace" / "wiki"
            index_path = wiki_root / "meta" / "aeon_index.jsonl"

            write_jsonl(
                promoted_path,
                [
                    self.build_record(
                        title="AI inference market",
                        canonical_entities=["OpenRouter"],
                        source_url="https://example.com/openrouter",
                        promotion_hash="prom-101",
                    )
                ],
            )

            first = ingest_promotions.ingest_promotions(
                promoted_path=promoted_path,
                wiki_root=wiki_root,
                index_path=index_path,
                partition_date="2026-05-25",
            )
            second = ingest_promotions.ingest_promotions(
                promoted_path=promoted_path,
                wiki_root=wiki_root,
                index_path=index_path,
                partition_date="2026-05-25",
            )

            self.assertEqual(first["selected_count"], 1)
            self.assertEqual(second["selected_count"], 0)
            self.assertEqual(second["wiki_writes"], 0)
            self.assertEqual(second["index_writes"], 0)

            wiki_files = sorted(wiki_root.glob("aeon/2026-05-25/*.md"))
            self.assertEqual(len(wiki_files), 1)
            first_path = first["written_artifacts"][0]["file_path"]
            self.assertEqual(first_path, wiki_files[0].relative_to(wiki_root))
            self.assertTrue(first_path.name.startswith("openrouter--"))
            self.assertTrue(first_path.name.endswith(".md"))
            self.assertEqual(wiki_files[0].read_text(encoding="utf-8"), first["written_artifacts"][0]["markdown"])

    def test_canonical_entities_and_metadata_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            promoted_path = temp_dir / "2026-05-25.jsonl"
            wiki_root = temp_dir / "workspace" / "wiki"
            index_path = wiki_root / "meta" / "aeon_index.jsonl"

            record = self.build_record(
                title="Venice/Dolphin thesis",
                canonical_entities=["Venice", "Dolphin"],
                source_url="https://example.com/venice-dolphin",
                promotion_hash="prom-201",
            )
            write_jsonl(promoted_path, [record])

            result = ingest_promotions.ingest_promotions(
                promoted_path=promoted_path,
                wiki_root=wiki_root,
                index_path=index_path,
                partition_date="2026-05-25",
            )

            artifact = result["written_artifacts"][0]
            markdown = artifact["markdown"]
            index_records = read_jsonl(index_path)

            self.assertIn("Venice", markdown)
            self.assertIn("Dolphin", markdown)
            self.assertIn("Related Narratives", markdown)
            self.assertIn("AI inference market", markdown)
            self.assertEqual(index_records[0]["canonical_entities"], ["Venice", "Dolphin"])
            self.assertEqual(index_records[0]["source_url"], "https://example.com/venice-dolphin")
            self.assertEqual(index_records[0]["promotion_reasons"], ["importance_score>=7", "source_priority=high"])
            self.assertEqual(index_records[0]["confidence"], 97)
            self.assertEqual(index_records[0]["narrative_membership"], ["Venice/Dolphin thesis", "AI inference market"])

    def test_rerun_idempotency_preserves_append_safe_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            promoted_path = temp_dir / "2026-05-25.jsonl"
            wiki_root = temp_dir / "workspace" / "wiki"
            index_path = wiki_root / "meta" / "aeon_index.jsonl"

            write_jsonl(
                promoted_path,
                [
                    self.build_record(
                        title="AI inference market",
                        canonical_entities=["OpenRouter"],
                        source_url="https://example.com/openrouter",
                        promotion_hash="prom-301",
                    )
                ],
            )

            first = ingest_promotions.ingest_promotions(
                promoted_path=promoted_path,
                wiki_root=wiki_root,
                index_path=index_path,
                partition_date="2026-05-25",
            )
            second = ingest_promotions.ingest_promotions(
                promoted_path=promoted_path,
                wiki_root=wiki_root,
                index_path=index_path,
                partition_date="2026-05-25",
            )

            self.assertEqual(first["selected_count"], 1)
            self.assertEqual(second["selected_count"], 0)
            self.assertEqual(len(read_jsonl(index_path)), 1)
            self.assertEqual(len(list(wiki_root.glob("aeon/2026-05-25/*.md"))), 1)


if __name__ == "__main__":
    unittest.main()
