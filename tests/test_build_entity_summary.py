import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "build_entity_summary.py"


def load_build_entity_summary_module():
    spec = importlib.util.spec_from_file_location(
        "build_entity_summary",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


build_entity_summary = load_build_entity_summary_module()


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


class BuildEntitySummaryTests(unittest.TestCase):
    def test_builds_cross_source_entity_summary_and_entity_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            log_path = temp_dir / "intake_log.jsonl"
            entity_summary_path = temp_dir / "entity_summary.json"
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
                    {
                        "item_id": "microsoft-2",
                        "source_type": "newsletter",
                        "source_name": "epsilon note",
                        "subject": "microsoft update",
                        "content_preview": "Microsoft received another mention in a separate newsletter.",
                        "importance_score": 5,
                        "timestamp": "2026-05-25T12:00:00Z",
                        "verticals": ["Cloud"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "microsoft-3",
                        "source_type": "pdf",
                        "source_name": "zeta memo",
                        "subject": "microsoft report",
                        "content_preview": "Microsoft appeared in the quarterly PDF report.",
                        "importance_score": 6,
                        "timestamp": "2026-05-25T13:00:00Z",
                        "verticals": ["Cloud"],
                        "digest_enabled": True,
                    },
                ],
            )

            summary = build_entity_summary.build_entity_summary(
                log_path=log_path,
                output_path=entity_summary_path,
                entity_dir=entities_dir,
            )

            self.assertTrue(entity_summary_path.exists())
            self.assertGreaterEqual(summary["entity_count"], 2)
            self.assertTrue(entities_dir.exists())
            self.assertGreaterEqual(len(list(entities_dir.glob("*.json"))), 2)

            top_emerging = summary["top_emerging_entities"][0]
            self.assertEqual(top_emerging["entity_name"], "OpenAI")
            self.assertEqual(top_emerging["mention_count"], 4)
            self.assertEqual(top_emerging["source_diversity"], 4)
            self.assertEqual(top_emerging["source_type_diversity"], 3)
            self.assertEqual(top_emerging["trend_label"], "rising")
            self.assertEqual(top_emerging["latest_mention_timestamp"], "2026-05-25T10:00:00+00:00")
            self.assertEqual(top_emerging["associated_verticals"], ["AI", "Cloud"])

            cross_source = summary["cross_source_entities"][0]
            self.assertEqual(cross_source["entity_name"], "OpenAI")
            self.assertGreaterEqual(cross_source["source_type_diversity"], 2)

            most_mentioned = summary["most_mentioned_entities"][0]
            self.assertEqual(most_mentioned["entity_name"], "OpenAI")
            self.assertEqual(most_mentioned["mention_count"], 4)

    def test_suppresses_common_words_and_keeps_configured_entities(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            log_path = temp_dir / "intake_log.jsonl"
            entity_summary_path = temp_dir / "entity_summary.json"
            entities_dir = temp_dir / "entities"

            noisy_text = "RT This It We If The A An I You They He She Today Now Here"

            write_jsonl(
                log_path,
                [
                    {
                        "item_id": "alpha-1",
                        "source_type": "twitter",
                        "source_name": "0xSammy",
                        "subject": noisy_text,
                        "content_preview": (
                            f"{noisy_text} model routing AI VC BTC"
                        ),
                        "importance_score": 2,
                        "timestamp": "2026-05-24T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "beta-1",
                        "source_type": "newsletter",
                        "source_name": "beta note",
                        "subject": noisy_text,
                        "content_preview": (
                            f"{noisy_text} Base chain and real world assets RWA ZK"
                        ),
                        "importance_score": 6,
                        "timestamp": "2026-05-25T10:00:00Z",
                        "verticals": ["Crypto"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "gamma-1",
                        "source_type": "pdf",
                        "source_name": "gamma memo",
                        "subject": noisy_text,
                        "content_preview": (
                            f"{noisy_text} OpenAI ETH VC model routing"
                        ),
                        "importance_score": 9,
                        "timestamp": "2026-05-26T10:00:00Z",
                        "verticals": ["AI", "Crypto"],
                        "digest_enabled": True,
                    },
                ],
            )

            summary = build_entity_summary.build_entity_summary(
                log_path=log_path,
                output_path=entity_summary_path,
                entity_dir=entities_dir,
            )

            entity_names = {entity["entity_name"] for entity in summary["entities"]}
            top_entity_names = {
                entity["entity_name"]
                for section_name in (
                    "top_emerging_entities",
                    "most_mentioned_entities",
                    "cross_source_entities",
                )
                for entity in summary[section_name]
            }

            bad_entities = {
                "RT",
                "This",
                "It",
                "We",
                "If",
                "The",
                "A",
                "An",
                "I",
                "You",
                "They",
                "He",
                "She",
                "Today",
                "Now",
                "Here",
            }

            self.assertTrue(bad_entities.isdisjoint(entity_names))
            self.assertTrue(bad_entities.isdisjoint(top_entity_names))
            self.assertIn("OpenRouter", entity_names)
            self.assertIn("0xSammy", entity_names)
            self.assertIn("AI", entity_names)
            self.assertIn("VC", entity_names)
            self.assertIn("BTC", entity_names)
            self.assertIn("ETH", entity_names)
            self.assertIn("RWA", entity_names)
            self.assertIn("ZK", entity_names)

    def test_aliases_collapse_to_canonical_entities(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            log_path = temp_dir / "intake_log.jsonl"
            entity_summary_path = temp_dir / "entity_summary.json"
            entities_dir = temp_dir / "entities"

            write_jsonl(
                log_path,
                [
                    {
                        "item_id": "venice-ai",
                        "source_type": "twitter",
                        "source_name": "alpha feed",
                        "subject": "market note",
                        "content_preview": "Venice AI is back in the mix.",
                        "importance_score": 4,
                        "timestamp": "2026-05-20T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "venice-vvv",
                        "source_type": "newsletter",
                        "source_name": "beta note",
                        "subject": "market note",
                        "content_preview": "VVV was mentioned in the morning brief.",
                        "importance_score": 4,
                        "timestamp": "2026-05-21T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "venice-diem",
                        "source_type": "pdf",
                        "source_name": "gamma memo",
                        "subject": "market note",
                        "content_preview": "DIEM stayed on the radar.",
                        "importance_score": 4,
                        "timestamp": "2026-05-22T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "dolphin",
                        "source_type": "twitter",
                        "source_name": "delta feed",
                        "subject": "market note",
                        "content_preview": "Dolphin showed up in a product update.",
                        "importance_score": 4,
                        "timestamp": "2026-05-23T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "dolphin-ai",
                        "source_type": "newsletter",
                        "source_name": "epsilon note",
                        "subject": "market note",
                        "content_preview": "Dolphin AI got another mention.",
                        "importance_score": 4,
                        "timestamp": "2026-05-24T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "dolphin-pod",
                        "source_type": "pdf",
                        "source_name": "zeta memo",
                        "subject": "market note",
                        "content_preview": "POD was referenced alongside $POD.",
                        "importance_score": 4,
                        "timestamp": "2026-05-25T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "dolphin-xpod",
                        "source_type": "twitter",
                        "source_name": "eta feed",
                        "subject": "market note",
                        "content_preview": "xPOD was part of the same thread.",
                        "importance_score": 4,
                        "timestamp": "2026-05-26T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "base",
                        "source_type": "twitter",
                        "source_name": "theta feed",
                        "subject": "market note",
                        "content_preview": "Base was discussed in the network update.",
                        "importance_score": 4,
                        "timestamp": "2026-05-27T10:00:00Z",
                        "verticals": ["DeFi"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "base-base",
                        "source_type": "newsletter",
                        "source_name": "iota note",
                        "subject": "market note",
                        "content_preview": "Coinbase Base added a new app surface.",
                        "importance_score": 4,
                        "timestamp": "2026-05-28T10:00:00Z",
                        "verticals": ["DeFi"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "rwa",
                        "source_type": "pdf",
                        "source_name": "kappa memo",
                        "subject": "market note",
                        "content_preview": "RWA continued to attract attention.",
                        "importance_score": 4,
                        "timestamp": "2026-05-29T10:00:00Z",
                        "verticals": ["RWA"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "rwa-tokenization",
                        "source_type": "twitter",
                        "source_name": "lambda feed",
                        "subject": "market note",
                        "content_preview": "tokenization was part of the discussion.",
                        "importance_score": 4,
                        "timestamp": "2026-05-30T10:00:00Z",
                        "verticals": ["RWA"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "rwa-tokenized-assets",
                        "source_type": "twitter",
                        "source_name": "mu feed",
                        "subject": "market note",
                        "content_preview": "tokenized assets were part of the same discussion.",
                        "importance_score": 4,
                        "timestamp": "2026-05-30T11:00:00Z",
                        "verticals": ["RWA"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "openrouter",
                        "source_type": "newsletter",
                        "source_name": "nu note",
                        "subject": "market note",
                        "content_preview": "OpenRouter kept improving the stack.",
                        "importance_score": 4,
                        "timestamp": "2026-05-31T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "openrouter-routing",
                        "source_type": "pdf",
                        "source_name": "xi memo",
                        "subject": "market note",
                        "content_preview": "inference routing and model routing were highlighted.",
                        "importance_score": 4,
                        "timestamp": "2026-06-01T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "noisy-oneoff",
                        "source_type": "twitter",
                        "source_name": "omicron feed",
                        "subject": "market note",
                        "content_preview": "Nebula is the only mention here.",
                        "importance_score": 2,
                        "timestamp": "2026-06-02T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                ],
            )

            summary = build_entity_summary.build_entity_summary(
                log_path=log_path,
                output_path=entity_summary_path,
                entity_dir=entities_dir,
            )

            entities_by_name = {
                entity["entity_name"]: entity
                for entity in summary["entities"]
            }
            entity_names = set(entities_by_name)

            self.assertTrue({"Venice", "Dolphin", "Base", "RWA", "OpenRouter"}.issubset(entity_names))
            self.assertNotIn("Venice AI", entity_names)
            self.assertNotIn("VVV", entity_names)
            self.assertNotIn("DIEM", entity_names)
            self.assertNotIn("Dolphin AI", entity_names)
            self.assertNotIn("$POD", entity_names)
            self.assertNotIn("Coinbase Base", entity_names)
            self.assertNotIn("tokenization", entity_names)
            self.assertNotIn("tokenized assets", entity_names)
            self.assertNotIn("inference routing", entity_names)
            self.assertNotIn("Nebula", entity_names)

            self.assertEqual(entities_by_name["Venice"]["mention_count"], 3)
            self.assertEqual(entities_by_name["Dolphin"]["mention_count"], 4)
            self.assertEqual(entities_by_name["Base"]["mention_count"], 2)
            self.assertEqual(entities_by_name["RWA"]["mention_count"], 3)
            self.assertEqual(entities_by_name["OpenRouter"]["mention_count"], 2)

            self.assertEqual(entities_by_name["Venice"]["entity_type"], "company")
            self.assertEqual(entities_by_name["Dolphin"]["entity_type"], "protocol")
            self.assertEqual(entities_by_name["Base"]["entity_type"], "network")
            self.assertEqual(entities_by_name["RWA"]["entity_type"], "theme")
            self.assertEqual(entities_by_name["OpenRouter"]["entity_type"], "platform")

            for canonical_name in ("Venice", "Dolphin", "Base", "RWA", "OpenRouter"):
                self.assertGreaterEqual(entities_by_name[canonical_name]["entity_confidence"], 0.95)

    def test_build_entity_summary_uses_safe_deterministic_filenames(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            log_path = temp_dir / "intake_log.jsonl"
            entity_summary_path = temp_dir / "entity_summary.json"
            entities_dir = temp_dir / "entities"

            write_jsonl(
                log_path,
                [
                    {
                        "item_id": "alpha-1",
                        "source_type": "twitter",
                        "source_name": "alpha feed",
                        "subject": "alpha item",
                        "content_preview": "alpha item",
                        "importance_score": 5,
                        "timestamp": "2026-05-25T10:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                    {
                        "item_id": "beta-1",
                        "source_type": "twitter",
                        "source_name": "beta feed",
                        "subject": "beta item",
                        "content_preview": "beta item",
                        "importance_score": 5,
                        "timestamp": "2026-05-25T11:00:00Z",
                        "verticals": ["AI"],
                        "digest_enabled": True,
                    },
                ],
            )

            long_entity_key = (
                "https://nitter.net/"
                + "very-long-segment-" * 20
                + "openai"
            )
            malformed_url_key = (
                "https://x.com/"
                + "bad-path-" * 18
                + "status/1234567890?utm_source=feed&ref=home"
            )
            repeated_key = "OpenAI"

            def fake_extract_entities(text, configured_entities=None):
                return [
                    {
                        "entity_key": long_entity_key,
                        "entity_name": long_entity_key,
                        "position": 0,
                    },
                    {
                        "entity_key": malformed_url_key,
                        "entity_name": malformed_url_key,
                        "position": 1,
                    },
                    {
                        "entity_key": repeated_key,
                        "entity_name": repeated_key,
                        "position": 2,
                    },
                    {
                        "entity_key": repeated_key,
                        "entity_name": repeated_key,
                        "position": 3,
                    },
                ]

            with mock.patch.object(
                build_entity_summary,
                "extract_entities",
                side_effect=fake_extract_entities,
            ):
                summary = build_entity_summary.build_entity_summary(
                    log_path=log_path,
                    output_path=entity_summary_path,
                    entity_dir=entities_dir,
                )

            self.assertTrue(entity_summary_path.exists())
            self.assertEqual(summary["entity_count"], 3)

            written_files = sorted(entities_dir.glob("*.json"))
            self.assertEqual(len(written_files), 3)

            expected_by_filename = {
                build_entity_summary.build_entity_filename(long_entity_key): long_entity_key,
                build_entity_summary.build_entity_filename(malformed_url_key): malformed_url_key,
                build_entity_summary.build_entity_filename(repeated_key): repeated_key,
            }

            self.assertEqual(
                {path.name for path in written_files},
                set(expected_by_filename),
            )

            for path in written_files:
                self.assertLessEqual(
                    len(path.name),
                    build_entity_summary.MAX_ENTITY_FILENAME_LENGTH,
                )
                self.assertNotIn("/", path.name)
                self.assertNotIn("\\", path.name)

                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["entity_key"], expected_by_filename[path.name])
                self.assertEqual(
                    path.name,
                    build_entity_summary.build_entity_filename(payload["entity_key"]),
                )


if __name__ == "__main__":
    unittest.main()
