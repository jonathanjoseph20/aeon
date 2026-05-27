import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "build_digest.py"
SLACK_MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "build_slack_digest_payload.py"


def load_module(module_name, module_path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


build_digest = load_module("build_digest", MODULE_PATH)
build_slack_digest_payload = load_module("build_slack_digest_payload", SLACK_MODULE_PATH)


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


class BuildDigestTests(unittest.TestCase):
    def test_writes_entity_sections_and_slack_payload_parses_them(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            log_path = temp_dir / "intake_log.jsonl"
            cluster_path = temp_dir / "topic_clusters.jsonl"
            entity_summary_path = temp_dir / "entity_summary.json"
            digest_path = temp_dir / "daily_digest.md"
            alerts_path = temp_dir / "alert_candidates.jsonl"
            hermes_dir = temp_dir / "hermes" / "promoted"
            entities_dir = temp_dir / "entities"

            write_jsonl(
                log_path,
                [
                    {
                        "item_id": "openai-1",
                        "source_type": "twitter",
                        "source_name": "alpha feed",
                        "subject": "openai expands partnerships",
                        "content_preview": "OpenAI announced a model update for enterprise teams.",
                        "importance_score": 2,
                        "timestamp": "2026-05-20T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "openai-2",
                        "source_type": "newsletter",
                        "source_name": "beta note",
                        "subject": "openai watch",
                        "content_preview": "OpenAI and Microsoft were discussed in the latest briefing.",
                        "importance_score": 3,
                        "timestamp": "2026-05-21T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "microsoft-1",
                        "source_type": "pdf",
                        "source_name": "gamma memo",
                        "subject": "market report",
                        "content_preview": "Microsoft added a cloud product update and OpenAI was cited again.",
                        "importance_score": 7,
                        "timestamp": "2026-05-24T10:00:00Z",
                        "verticals": ["Cloud"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "openai-3",
                        "source_type": "twitter",
                        "source_name": "delta feed",
                        "subject": "openai momentum",
                        "content_preview": "OpenAI kept gaining attention across the week.",
                        "importance_score": 8,
                        "timestamp": "2026-05-25T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                ],
            )

            write_jsonl(
                alerts_path,
                [
                    {
                        "item_id": "alert-1",
                        "subject": "alert",
                    }
                ],
            )

            hermes_dir.mkdir(parents=True, exist_ok=True)
            write_jsonl(
                hermes_dir / "2026-05-25.jsonl",
                [
                    {
                        "item_id": "hermes-1",
                        "subject": "hermes",
                    }
                ],
            )

            result = build_digest.write_digest(
                log_path=log_path,
                cluster_path=cluster_path,
                entity_summary_path=entity_summary_path,
                digest_path=digest_path,
            )

            digest_text = digest_path.read_text(encoding="utf-8")
            self.assertIn("## Top Emerging Entities", digest_text)
            self.assertIn("## Most-mentioned Entities", digest_text)
            self.assertIn("## Cross-source Entities", digest_text)
            self.assertIn("**OpenAI**", digest_text)
            self.assertEqual(result["entity_section_count"], 3)

            payload_result = build_slack_digest_payload.build_slack_digest_payload(
                digest_path=digest_path,
                alerts_path=alerts_path,
                hermes_dir=hermes_dir,
                outbox_dir=temp_dir / "outbox",
            )

            payload = payload_result["payload"]
            self.assertEqual(len(payload["entity_section_summaries"]), 3)
            self.assertIn("Top Emerging Entities: OpenAI", payload["text"])


if __name__ == "__main__":
    unittest.main()
