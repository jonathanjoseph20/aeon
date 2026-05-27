import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "hermes" / "build_synthesis.py"


def load_module(module_name, module_path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


build_synthesis = load_module("build_synthesis", MODULE_PATH)


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


def write_markdown(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                f"title: {json.dumps(record['title'])}",
                f"source: {json.dumps(record['source'])}",
                f"timestamp: {json.dumps(record['timestamp'])}",
                "canonical_entities:",
                *[f"  - {json.dumps(value)}" for value in record["canonical_entities"]],
                "verticals:",
                *[f"  - {json.dumps(value)}" for value in record["verticals"]],
                "promotion_reasons:",
                *[f"  - {json.dumps(value)}" for value in record["promotion_reasons"]],
                f"confidence: {record['confidence']}",
                "narrative_membership:",
                *[f"  - {json.dumps(value)}" for value in record["narrative_membership"]],
                f"source_url: {json.dumps(record['source_url'])}",
                f"promotion_hash: {json.dumps(record['memory_id'])}",
                f"memory_id: {json.dumps(record['memory_id'])}",
                "---",
                "",
                f"# {record['title']}",
                "",
                "## Source",
                f"- Source: {record['source']}",
                f"- Timestamp: {record['timestamp']}",
                "",
                "## Canonical Entities",
                *[f"- {value}" for value in record["canonical_entities"]],
                "",
                "## Verticals",
                *[f"- {value}" for value in record["verticals"]],
                "",
                "## Promotion Reasons",
                *[f"- {value}" for value in record["promotion_reasons"]],
                "",
                "## Confidence",
                f"- {record['confidence']}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


class BuildSynthesisTests(unittest.TestCase):
    def build_records(self):
        return [
            {
                "memory_id": "venice-001",
                "title": "Venice thesis update",
                "source": "Alpha Research (newsletter)",
                "timestamp": "2026-05-25T10:00:00+00:00",
                "source_url": "https://example.com/venice-1",
                "canonical_entities": ["Venice", "Dolphin"],
                "verticals": ["AI"],
                "promotion_reasons": ["importance_score>=7"],
                "confidence": 96,
                "narrative_membership": ["Venice/Dolphin thesis"],
                "source_type": "newsletter",
                "partition_date": "2026-05-25",
                "file_path": "aeon/2026-05-25/venice--001.md",
            },
            {
                "memory_id": "venice-002",
                "title": "Venice thesis follow-up",
                "source": "Beta Research (twitter)",
                "timestamp": "2026-05-25T14:00:00+00:00",
                "source_url": "https://example.com/venice-2",
                "canonical_entities": ["Venice", "Dolphin"],
                "verticals": ["AI"],
                "promotion_reasons": ["source_priority=high"],
                "confidence": 93,
                "narrative_membership": ["Venice/Dolphin thesis"],
                "source_type": "twitter",
                "partition_date": "2026-05-25",
                "file_path": "aeon/2026-05-25/venice--002.md",
            },
            {
                "memory_id": "openrouter-001",
                "title": "AI inference market update",
                "source": "Gamma Notes (pdf)",
                "timestamp": "2026-05-25T12:00:00+00:00",
                "source_url": "https://example.com/openrouter-1",
                "canonical_entities": ["OpenRouter"],
                "verticals": ["AI"],
                "promotion_reasons": ["importance_score>=7"],
                "confidence": 88,
                "narrative_membership": ["AI inference market"],
                "source_type": "pdf",
                "partition_date": "2026-05-25",
                "file_path": "aeon/2026-05-25/openrouter--001.md",
            },
            {
                "memory_id": "stablecoin-001",
                "title": "Stablecoin watch",
                "source": "Delta Brief (newsletter)",
                "timestamp": "2026-05-26T11:00:00+00:00",
                "source_url": "https://example.com/stablecoin-1",
                "canonical_entities": ["Stablecoin Desk"],
                "verticals": ["Macro"],
                "promotion_reasons": ["source_priority=high"],
                "confidence": 91,
                "narrative_membership": ["stablecoin regulation"],
                "source_type": "newsletter",
                "partition_date": "2026-05-26",
                "file_path": "aeon/2026-05-26/stablecoin--001.md",
            },
        ]

    def write_fixture(self, temp_dir):
        temp_dir = Path(temp_dir)
        wiki_root = temp_dir / "workspace" / "wiki"
        index_path = wiki_root / "meta" / "aeon_index.jsonl"
        narrative_summary_path = temp_dir / "data" / "processed" / "narrative_summary.json"
        records = self.build_records()

        write_jsonl(index_path, records)

        for record in records:
            write_markdown(wiki_root / record["file_path"], record)

        write_json(
            narrative_summary_path,
            {
                "generated_at": "2026-05-26T00:00:00+00:00",
                "entities": [
                    {"canonical_name": "Venice", "priority_score": 120},
                    {"canonical_name": "Dolphin", "priority_score": 110},
                    {"canonical_name": "OpenRouter", "priority_score": 80},
                    {"canonical_name": "Stablecoin Desk", "priority_score": 70},
                ],
                "narratives": [
                    {
                        "narrative_name": "Venice/Dolphin thesis",
                        "priority_score": 540,
                        "mention_count": 2,
                        "source_count": 2,
                    },
                    {
                        "narrative_name": "AI inference market",
                        "priority_score": 420,
                        "mention_count": 1,
                        "source_count": 1,
                    },
                    {
                        "narrative_name": "stablecoin regulation",
                        "priority_score": 390,
                        "mention_count": 1,
                        "source_count": 1,
                    },
                ],
                "top_narratives": [
                    {"narrative_name": "Venice/Dolphin thesis", "priority_score": 540},
                    {"narrative_name": "AI inference market", "priority_score": 420},
                ],
            },
        )

        return wiki_root, index_path, narrative_summary_path

    def test_reads_index_and_produces_daily_and_weekly_synthesis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wiki_root, index_path, narrative_summary_path = self.write_fixture(temp_dir)

            result = build_synthesis.build_synthesis(
                wiki_root=wiki_root,
                index_path=index_path,
                narrative_summary_path=narrative_summary_path,
                target_date="2026-05-25",
            )

            weekly_key = f"{date.fromisoformat('2026-05-25').isocalendar().year:04d}-{date.fromisoformat('2026-05-25').isocalendar().week:02d}"

            self.assertEqual(result["index_record_count"], 4)
            self.assertEqual(result["daily_scope_record_count"], 3)
            self.assertEqual(result["weekly_scope_record_count"], 4)
            self.assertTrue(result["daily_output_path"].exists())
            self.assertTrue(result["weekly_output_path"].exists())
            self.assertEqual(result["daily_output_path"].name, "2026-05-25.md")
            self.assertEqual(result["weekly_output_path"].name, f"{weekly_key}.md")
            self.assertIn("## Executive Summary", result["daily_markdown"])
            self.assertIn("## Top Narratives", result["daily_markdown"])
            self.assertIn("Venice/Dolphin thesis", result["daily_markdown"])
            self.assertIn("AI inference market", result["daily_markdown"])
            self.assertIn("## Suggested Follow-ups for Midas", result["daily_markdown"])
            self.assertIn("Review `Venice/Dolphin thesis`", result["daily_markdown"])
            self.assertIn("stablecoin regulation", result["weekly_markdown"])

    def test_rerun_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wiki_root, index_path, narrative_summary_path = self.write_fixture(temp_dir)

            first = build_synthesis.build_synthesis(
                wiki_root=wiki_root,
                index_path=index_path,
                narrative_summary_path=narrative_summary_path,
                target_date="2026-05-25",
            )
            second = build_synthesis.build_synthesis(
                wiki_root=wiki_root,
                index_path=index_path,
                narrative_summary_path=narrative_summary_path,
                target_date="2026-05-25",
            )

            self.assertTrue(first["daily_written"])
            self.assertTrue(first["weekly_written"])
            self.assertFalse(second["daily_written"])
            self.assertFalse(second["weekly_written"])
            self.assertEqual(first["daily_markdown"], second["daily_markdown"])
            self.assertEqual(first["weekly_markdown"], second["weekly_markdown"])


if __name__ == "__main__":
    unittest.main()
