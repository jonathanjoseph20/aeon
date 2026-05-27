import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "build_narrative_summary.py"
SLACK_MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "build_slack_digest_payload.py"


def load_module(module_name, module_path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


build_narrative_summary = load_module("build_narrative_summary", MODULE_PATH)
build_slack_digest_payload = load_module("build_slack_digest_payload", SLACK_MODULE_PATH)


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


class BuildNarrativeSummaryTests(unittest.TestCase):
    def _build_venice_dolphin_records(self, count, *, start_index=0):
        records = []

        for index in range(count):
            if index % 2 == 0:
                name = "Venice"
                alias = "Venice AI"
                verticals = ["AI", "Portfolio"]
            else:
                name = "Dolphin"
                alias = "Dolphin AI"
                verticals = ["AI", "Portfolio"]

            records.append(
                {
                    "item_id": f"{name.lower()}-{start_index + index:03d}",
                    "source_type": "twitter",
                    "source_name": f"{name} Desk {index:02d}",
                    "subject": f"{alias} thesis update",
                    "content_preview": f"{alias} is gaining attention across desks.",
                    "importance_score": 8,
                    "timestamp": f"2026-05-25T{10 + index:02d}:00:00Z",
                    "verticals": verticals,
                    "digest_enabled": True,
                }
            )

        return records

    def _build_base_records(self, count, *, start_index=0):
        records = []

        for index in range(count):
            records.append(
                {
                    "item_id": f"base-{start_index + index:03d}",
                    "source_type": "newsletter",
                    "source_name": f"Base Note {index:02d}",
                    "subject": "Base ecosystem update",
                    "content_preview": "Coinbase Base ecosystem and Base network momentum.",
                    "importance_score": 6,
                    "timestamp": f"2026-05-25T{12 + index:02d}:00:00Z",
                    "verticals": ["DeFi", "Portfolio"],
                    "digest_enabled": True,
                }
            )

        return records

    def _build_rwa_records(self, count, *, start_index=0):
        records = []

        for index in range(count):
            records.append(
                {
                    "item_id": f"rwa-{start_index + index:03d}",
                    "source_type": "pdf",
                    "source_name": f"RWA Memo {index:02d}",
                    "subject": "Tokenization thesis",
                    "content_preview": "RWA tokenization and real world assets keep moving.",
                    "importance_score": 7,
                    "timestamp": f"2026-05-25T{14 + index:02d}:00:00Z",
                    "verticals": ["RWA"],
                    "digest_enabled": True,
                }
            )

        return records

    def test_new_entity_becomes_new_narrative(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            log_path = temp_dir / "intake_log.jsonl"
            alerts_path = temp_dir / "alert_candidates.jsonl"
            hermes_dir = temp_dir / "hermes" / "promoted"
            entity_summary_path = temp_dir / "entity_summary.json"
            narrative_summary_path = temp_dir / "narrative_summary.json"

            write_jsonl(log_path, self._build_venice_dolphin_records(2))
            write_jsonl(alerts_path, [])
            write_jsonl(hermes_dir / "2026-05-25.jsonl", [])

            summary = build_narrative_summary.build_narrative_summary(
                log_path=log_path,
                entity_summary_path=entity_summary_path,
                output_path=narrative_summary_path,
                alerts_path=alerts_path,
                hermes_dir=hermes_dir,
            )

            self.assertTrue(narrative_summary_path.exists())
            self.assertGreaterEqual(summary["narrative_count"], 1)
            top_narrative = summary["top_narratives"][0]
            self.assertEqual(top_narrative["narrative_name"], "Venice/Dolphin thesis")
            self.assertEqual(top_narrative["trend_status"], "new")
            self.assertGreaterEqual(top_narrative["mention_count"], 2)

            entity_trends = {
                entity["canonical_name"]: entity["trend_status"]
                for entity in summary["entities"]
            }
            self.assertEqual(entity_trends["Venice"], "new")
            self.assertEqual(entity_trends["Dolphin"], "new")

    def test_repeated_entity_becomes_stable_when_counts_hold(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            log_path = temp_dir / "intake_log.jsonl"
            alerts_path = temp_dir / "alert_candidates.jsonl"
            hermes_dir = temp_dir / "hermes" / "promoted"
            entity_summary_path = temp_dir / "entity_summary.json"
            narrative_summary_path = temp_dir / "narrative_summary.json"

            write_jsonl(log_path, self._build_venice_dolphin_records(4))
            write_jsonl(alerts_path, [])
            write_jsonl(hermes_dir / "2026-05-25.jsonl", [])

            write_json(
                narrative_summary_path,
                {
                    "generated_at": "2026-05-24T00:00:00Z",
                    "entities": [
                        {
                            "entity_key": "venice",
                            "mention_count": 4,
                            "source_count": 4,
                            "first_seen": "2026-05-20T10:00:00Z",
                            "last_seen": "2026-05-24T10:00:00Z",
                        }
                    ],
                    "narratives": [
                        {
                            "narrative_name": "Venice/Dolphin thesis",
                            "mention_count": 4,
                            "source_count": 4,
                            "first_seen": "2026-05-20T10:00:00Z",
                            "last_seen": "2026-05-24T10:00:00Z",
                        }
                    ],
                    "top_narratives": [],
                },
            )

            summary = build_narrative_summary.build_narrative_summary(
                log_path=log_path,
                entity_summary_path=entity_summary_path,
                output_path=narrative_summary_path,
                alerts_path=alerts_path,
                hermes_dir=hermes_dir,
            )

            top_narrative = summary["top_narratives"][0]
            self.assertEqual(top_narrative["narrative_name"], "Venice/Dolphin thesis")
            self.assertEqual(top_narrative["trend_status"], "stable")

    def test_repeated_entity_becomes_rising_when_counts_jump(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            log_path = temp_dir / "intake_log.jsonl"
            alerts_path = temp_dir / "alert_candidates.jsonl"
            hermes_dir = temp_dir / "hermes" / "promoted"
            entity_summary_path = temp_dir / "entity_summary.json"
            narrative_summary_path = temp_dir / "narrative_summary.json"

            write_jsonl(log_path, self._build_venice_dolphin_records(8))
            write_jsonl(alerts_path, [])
            write_jsonl(hermes_dir / "2026-05-25.jsonl", [])

            write_json(
                narrative_summary_path,
                {
                    "generated_at": "2026-05-24T00:00:00Z",
                    "entities": [
                        {
                            "entity_key": "venice",
                            "mention_count": 2,
                            "source_count": 2,
                            "first_seen": "2026-05-20T10:00:00Z",
                            "last_seen": "2026-05-24T10:00:00Z",
                        }
                    ],
                    "narratives": [
                        {
                            "narrative_name": "Venice/Dolphin thesis",
                            "mention_count": 2,
                            "source_count": 2,
                            "first_seen": "2026-05-20T10:00:00Z",
                            "last_seen": "2026-05-24T10:00:00Z",
                        }
                    ],
                    "top_narratives": [],
                },
            )

            summary = build_narrative_summary.build_narrative_summary(
                log_path=log_path,
                entity_summary_path=entity_summary_path,
                output_path=narrative_summary_path,
                alerts_path=alerts_path,
                hermes_dir=hermes_dir,
            )

            top_narrative = summary["top_narratives"][0]
            self.assertEqual(top_narrative["narrative_name"], "Venice/Dolphin thesis")
            self.assertEqual(top_narrative["trend_status"], "rising")
            self.assertGreater(top_narrative["mention_count"], 2)

    def test_low_confidence_unknowns_do_not_create_narratives(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            log_path = temp_dir / "intake_log.jsonl"
            alerts_path = temp_dir / "alert_candidates.jsonl"
            hermes_dir = temp_dir / "hermes" / "promoted"
            entity_summary_path = temp_dir / "entity_summary.json"
            narrative_summary_path = temp_dir / "narrative_summary.json"

            write_jsonl(
                log_path,
                [
                    {
                        "item_id": "unknown-1",
                        "source_type": "twitter",
                        "source_name": "noise feed",
                        "subject": "Nebula is the only mention here.",
                        "content_preview": "Nebula is the only mention here.",
                        "importance_score": 2,
                        "timestamp": "2026-05-25T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    }
                ],
            )
            write_jsonl(alerts_path, [])
            write_jsonl(hermes_dir / "2026-05-25.jsonl", [])

            summary = build_narrative_summary.build_narrative_summary(
                log_path=log_path,
                entity_summary_path=entity_summary_path,
                output_path=narrative_summary_path,
                alerts_path=alerts_path,
                hermes_dir=hermes_dir,
            )

            self.assertEqual(summary["entity_count"], 0)
            self.assertEqual(summary["narrative_count"], 0)
            self.assertEqual(summary["top_narratives"], [])

    def test_promoted_items_increase_narrative_priority(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            log_path = temp_dir / "intake_log.jsonl"
            alerts_path = temp_dir / "alert_candidates.jsonl"
            hermes_dir = temp_dir / "hermes" / "promoted"
            entity_summary_path = temp_dir / "entity_summary.json"
            narrative_summary_path = temp_dir / "narrative_summary.json"

            write_jsonl(
                log_path,
                self._build_base_records(2) + self._build_rwa_records(2),
            )
            write_jsonl(
                alerts_path,
                [
                    {
                        "item_id": "alert-1",
                        "source_name": "RWA Memo 00",
                        "subject": "Tokenization thesis",
                        "content_preview": "RWA tokenization and real world assets keep moving.",
                    }
                ],
            )
            write_jsonl(
                hermes_dir / "2026-05-25.jsonl",
                [
                    {
                        "promotion_hash": "hermes-001",
                        "source_name": "RWA Memo 00",
                        "subject": "Tokenization thesis",
                        "summary": "RWA tokenization and real world assets keep moving.",
                        "preview": "RWA tokenization and real world assets keep moving.",
                    }
                ],
            )

            summary = build_narrative_summary.build_narrative_summary(
                log_path=log_path,
                entity_summary_path=entity_summary_path,
                output_path=narrative_summary_path,
                alerts_path=alerts_path,
                hermes_dir=hermes_dir,
            )

            top_narrative = summary["top_narratives"][0]
            self.assertEqual(top_narrative["narrative_name"], "RWA/tokenization")
            self.assertGreaterEqual(top_narrative["promotion_count"], 1)
            self.assertGreater(top_narrative["priority_score"], summary["narratives"][1]["priority_score"])

    def test_slack_payload_includes_top_narratives_compactly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            digest_path = temp_dir / "daily_digest.md"
            digest_path.write_text(
                "\n".join(
                    [
                        "# Daily Intelligence Digest",
                        "",
                        "Generated: 2026-05-25T23:32:21Z",
                        "",
                        "## AI",
                        "",
                        "- `item-1` — **Desk** — headline — *High Signal / high / score 9* — tags: AI — preview...",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            input_log_path = temp_dir / "intake_log.jsonl"
            write_jsonl(
                input_log_path,
                [
                    {
                        "item_id": "item-1",
                        "subject": "headline",
                        "importance_score": 9,
                    }
                ],
            )

            alerts_path = temp_dir / "alert_candidates.jsonl"
            write_jsonl(alerts_path, [])
            hermes_dir = temp_dir / "hermes" / "promoted"
            write_jsonl(hermes_dir / "2026-05-25.jsonl", [])

            write_json(
                temp_dir / "narrative_summary.json",
                {
                    "generated_at": "2026-05-25T23:32:21Z",
                    "top_narratives": [
                        {
                            "narrative_name": "Venice/Dolphin thesis",
                            "trend_status": "rising",
                            "source_count": 6,
                            "promotion_count": 2,
                            "alert_count": 0,
                        },
                        {
                            "narrative_name": "RWA/tokenization",
                            "trend_status": "stable",
                            "source_count": 18,
                            "promotion_count": 0,
                            "alert_count": 4,
                        },
                    ],
                },
            )

            result = build_slack_digest_payload.build_slack_digest_payload(
                digest_path=digest_path,
                input_log_path=input_log_path,
                alerts_path=alerts_path,
                hermes_dir=hermes_dir,
                outbox_dir=temp_dir / "outbox",
            )

            payload = result["payload"]

            self.assertEqual(len(payload["narrative_section_summaries"]), 2)
            self.assertIn("Top Narratives:", payload["text"])
            self.assertIn("Venice/Dolphin thesis: rising, 6 sources, 2 promotions", payload["text"])
            self.assertIn("RWA/tokenization: stable, 18 sources, 4 alerts", payload["text"])


if __name__ == "__main__":
    unittest.main()
