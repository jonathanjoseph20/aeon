import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "hermes" / "build_tasks.py"


def load_module(module_name, module_path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


build_tasks = load_module("build_tasks", MODULE_PATH)


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

    lines.extend(
        [
            "",
            "## Suggested Follow-ups for Midas",
            *[
                line
                for line in narrative_lines[:1]
            ],
            "",
        ]
    )

    path.write_text("\n".join(lines), encoding="utf-8")


class BuildTasksTests(unittest.TestCase):
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

        daily_markdown = "\n".join(
            [
                "# Hermes Synthesis Memo",
                "",
                "## Top Narratives",
                "- `OpenRouter expansion` | priority `96` | confidence `94` | sources `3` | entities `OpenRouter, AI` | records `3`",
                "- `Venice/Dolphin thesis` | priority `88` | confidence `95` | sources `2` | entities `Venice, Dolphin` | records `2`",
                "",
                "## Portfolio / Watchlist Relevance",
                "- `Venice` | priority `130` | confidence `97` | sources `4` | narratives `Venice/Dolphin thesis` | records `2`",
                "- `OpenRouter` | priority `82` | confidence `94` | sources `3` | narratives `OpenRouter expansion` | records `2`",
                "",
                "## Suggested Follow-ups for Midas",
                "- Review `OpenRouter expansion` for Midas: `3` sources, confidence `94`, entity priority `82`.",
                "",
            ]
        )

        weekly_markdown = "\n".join(
            [
                "# Hermes Synthesis Memo",
                "",
                "## Top Narratives",
                "- `OpenRouter expansion` | priority `96` | confidence `94` | sources `3` | entities `OpenRouter, AI` | records `3`",
                "",
                "## Portfolio / Watchlist Relevance",
                "- `Venice` | priority `130` | confidence `97` | sources `4` | narratives `Venice/Dolphin thesis` | records `2`",
                "",
                "## Suggested Follow-ups for Midas",
                "- Review `Venice/Dolphin thesis` for Midas: `2` sources, confidence `95`, entity priority `130`.",
                "",
            ]
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

    def test_rising_narrative_generates_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wiki_root, index_path, narrative_summary_path = self.write_fixture(temp_dir)

            result = build_tasks.build_tasks(
                wiki_root=wiki_root,
                index_path=index_path,
                narrative_summary_path=narrative_summary_path,
                target_date="2026-05-25",
            )

            self.assertTrue(result["output_path"].exists())
            self.assertGreaterEqual(result["task_count"], 2)
            self.assertEqual(result["tasks"][0]["narrative"], "Venice")

            narratives = {task["narrative"] for task in result["tasks"]}
            self.assertIn("OpenRouter expansion", narratives)

    def test_duplicate_rerun_suppression(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wiki_root, index_path, narrative_summary_path = self.write_fixture(temp_dir)

            first = build_tasks.build_tasks(
                wiki_root=wiki_root,
                index_path=index_path,
                narrative_summary_path=narrative_summary_path,
                target_date="2026-05-25",
            )
            second = build_tasks.build_tasks(
                wiki_root=wiki_root,
                index_path=index_path,
                narrative_summary_path=narrative_summary_path,
                target_date="2026-05-25",
            )

            self.assertTrue(first["output_written"])
            self.assertFalse(second["output_written"])
            self.assertEqual(first["tasks"], second["tasks"])

    def test_deterministic_task_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wiki_root, index_path, narrative_summary_path = self.write_fixture(temp_dir)

            first = build_tasks.build_tasks(
                wiki_root=wiki_root,
                index_path=index_path,
                narrative_summary_path=narrative_summary_path,
                target_date="2026-05-25",
            )
            second = build_tasks.build_tasks(
                wiki_root=wiki_root,
                index_path=index_path,
                narrative_summary_path=narrative_summary_path,
                target_date="2026-05-25",
            )

            self.assertEqual(
                [task["task_id"] for task in first["tasks"]],
                [task["task_id"] for task in second["tasks"]],
            )

    def test_high_priority_entities_rank_higher(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wiki_root, index_path, narrative_summary_path = self.write_fixture(temp_dir)

            result = build_tasks.build_tasks(
                wiki_root=wiki_root,
                index_path=index_path,
                narrative_summary_path=narrative_summary_path,
                target_date="2026-05-25",
            )

            top_task = result["tasks"][0]
            second_task = result["tasks"][1]

            self.assertGreaterEqual(top_task["priority"], second_task["priority"])
            self.assertEqual(top_task["narrative"], "Venice")

    def test_synthesis_links_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wiki_root, index_path, narrative_summary_path = self.write_fixture(temp_dir)

            result = build_tasks.build_tasks(
                wiki_root=wiki_root,
                index_path=index_path,
                narrative_summary_path=narrative_summary_path,
                target_date="2026-05-25",
            )

            reason = result["tasks"][0]["reason"]
            self.assertIn("workspace/wiki/synthesis/daily/2026-05-25.md", reason)
            self.assertIn("workspace/wiki/synthesis/weekly/2026-22.md", reason)


if __name__ == "__main__":
    unittest.main()
