import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "build_slack_digest_payload.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_build_slack_digest_payload_module():
    spec = importlib.util.spec_from_file_location(
        "build_slack_digest_payload",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


build_slack_digest_payload = load_build_slack_digest_payload_module()


class BuildSlackDigestPayloadTests(unittest.TestCase):
    def setUp(self):
        self.digest_fixture = FIXTURES_DIR / "daily_digest_sample.md"
        self.alerts_fixture = FIXTURES_DIR / "alert_candidates_sample.jsonl"
        self.hermes_fixture = FIXTURES_DIR / "hermes_promoted_2026-05-25.jsonl"

    def _prepare_temp_inputs(self, temp_dir):
        temp_dir = Path(temp_dir)

        digest_path = temp_dir / "daily_digest.md"
        digest_path.write_text(self.digest_fixture.read_text(encoding="utf-8"), encoding="utf-8")

        input_log_path = temp_dir / "intake_log.jsonl"
        input_log_path.write_text(
            "\n".join(
                json.dumps(
                    {
                        "item_id": f"intake-{index:02d}",
                        "subject": f"Intake {index}",
                        "importance_score": 3 + (index % 4),
                    }
                )
                for index in range(10)
            )
            + "\n",
            encoding="utf-8",
        )

        alerts_path = temp_dir / "alert_candidates.jsonl"
        alerts_path.write_text(self.alerts_fixture.read_text(encoding="utf-8"), encoding="utf-8")

        hermes_dir = temp_dir / "hermes" / "promoted"
        hermes_dir.mkdir(parents=True, exist_ok=True)
        hermes_path = hermes_dir / "2026-05-25.jsonl"
        hermes_path.write_text(self.hermes_fixture.read_text(encoding="utf-8"), encoding="utf-8")

        return digest_path, input_log_path, alerts_path, hermes_dir

    def test_builds_payload_and_writes_outbox_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            digest_path, input_log_path, alerts_path, hermes_dir = self._prepare_temp_inputs(temp_dir)
            outbox_dir = temp_dir / "outbox" / "slack" / "daily-intel-digest"

            result = build_slack_digest_payload.build_slack_digest_payload(
                digest_path=digest_path,
                input_log_path=input_log_path,
                alerts_path=alerts_path,
                hermes_dir=hermes_dir,
                outbox_dir=outbox_dir,
            )

            payload = result["payload"]
            output_path = result["output_path"]

            self.assertEqual(payload["title"], "Daily Intelligence Digest")
            self.assertEqual(payload["date"], "2026-05-25")
            self.assertEqual(payload["total_intake_items"], 10)
            self.assertEqual(payload["top_alerts_count"], 2)
            self.assertEqual(payload["promoted_to_hermes_count"], 3)
            self.assertEqual(payload["promotion_rate"], 0.3)
            self.assertEqual(payload["promotion_rate_percent"], 30.0)
            self.assertEqual(
                payload["full_digest_path"],
                str(digest_path),
            )
            self.assertEqual(
                payload["grouped_vertical_summaries"],
                [
                    {
                        "vertical": "Macro",
                        "item_count": 2,
                        "summary": 'Macro Desk / CPI week ahead; +1 more',
                    },
                    {
                        "vertical": "Portfolio",
                        "item_count": 1,
                        "summary": 'Peter Attia / What Exactly is "Longevity"?',
                    },
                ],
            )
            self.assertEqual(
                payload["text"],
                'Daily Intelligence Digest (2026-05-25) | 10 intake items | 2 alerts | 3 Hermes promotions | promotion rate 30.0% | Macro: Macro Desk / CPI week ahead; +1 more | Portfolio: Peter Attia / What Exactly is "Longevity"?',
            )

            build_slack_digest_payload.write_payload(output_path, payload)
            self.assertTrue(output_path.exists())
            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8")),
                payload,
            )

    def test_preview_mode_prints_payload_without_writing_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            digest_path, input_log_path, alerts_path, hermes_dir = self._prepare_temp_inputs(temp_dir)
            outbox_dir = temp_dir / "outbox" / "slack" / "daily-intel-digest"

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = build_slack_digest_payload.main(
                    [
                        "--digest-path",
                        str(digest_path),
                        "--input-log",
                        str(input_log_path),
                        "--alerts-path",
                        str(alerts_path),
                        "--hermes-dir",
                        str(hermes_dir),
                        "--outbox-dir",
                        str(outbox_dir),
                        "--preview",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertFalse((outbox_dir / "2026-05-25.json").exists())

            printed_payload = json.loads(stdout.getvalue())
            self.assertEqual(printed_payload["date"], "2026-05-25")
            self.assertEqual(printed_payload["total_intake_items"], 10)
            self.assertEqual(printed_payload["top_alerts_count"], 2)
            self.assertEqual(printed_payload["promoted_to_hermes_count"], 3)
            self.assertEqual(printed_payload["promotion_rate_percent"], 30.0)

    def test_includes_entity_sections_in_payload_text(self):
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
                        "## Topic Clusters",
                        "",
                        "- **3 related items** — keywords: alpha, beta, gamma",
                        "",
                        "## Macro",
                        "",
                        "- `macro-001` — **Macro Desk** — CPI week ahead — *High Signal / high / score 9* — tags: Macro — Rate markets are watching the next CPI print and Fed path.",
                        "",
                        "## Top Emerging Entities",
                        "",
                        "- **OpenAI** — trend: rising — mentions: 4 — sources: 3 — avg importance: 5.5 — latest: 2026-05-25T10:00:00Z — verticals: AI, Cloud",
                        "- **Microsoft** — trend: stable — mentions: 3 — sources: 2 — avg importance: 6.0 — latest: 2026-05-25T13:00:00Z — verticals: Cloud",
                        "",
                        "## Most-mentioned Entities",
                        "",
                        "- **OpenAI** — trend: rising — mentions: 4 — sources: 3 — avg importance: 5.5 — latest: 2026-05-25T10:00:00Z — verticals: AI, Cloud",
                        "",
                        "## Cross-source Entities",
                        "",
                        "- **OpenAI** — trend: rising — mentions: 4 — sources: 3 — avg importance: 5.5 — latest: 2026-05-25T10:00:00Z — verticals: AI, Cloud",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            alerts_path = temp_dir / "alert_candidates.jsonl"
            alerts_path.write_text(self.alerts_fixture.read_text(encoding="utf-8"), encoding="utf-8")

            input_log_path = temp_dir / "intake_log.jsonl"
            input_log_path.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "item_id": f"entity-{index}",
                            "subject": f"Entity {index}",
                            "importance_score": 4,
                        }
                    )
                    for index in range(6)
                )
                + "\n",
                encoding="utf-8",
            )

            hermes_dir = temp_dir / "hermes" / "promoted"
            hermes_dir.mkdir(parents=True, exist_ok=True)
            hermes_path = hermes_dir / "2026-05-25.jsonl"
            hermes_path.write_text(self.hermes_fixture.read_text(encoding="utf-8"), encoding="utf-8")

            result = build_slack_digest_payload.build_slack_digest_payload(
                digest_path=digest_path,
                input_log_path=input_log_path,
                alerts_path=alerts_path,
                hermes_dir=hermes_dir,
                outbox_dir=temp_dir / "outbox" / "slack" / "daily-intel-digest",
            )

            payload = result["payload"]

            self.assertEqual(len(payload["entity_section_summaries"]), 3)
            self.assertEqual(payload["entity_section_summaries"][0]["section"], "Top Emerging Entities")
            self.assertEqual(payload["entity_section_summaries"][0]["item_count"], 2)
            self.assertIn(
                "Top Emerging Entities: OpenAI (rising, 4 mentions, 3 sources)",
                payload["text"],
            )


if __name__ == "__main__":
    unittest.main()
