import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "fetch_twitter.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fetch_twitter_module():
    spec = importlib.util.spec_from_file_location("fetch_twitter", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


fetch_twitter = load_fetch_twitter_module()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


class FetchTwitterFixtureTests(unittest.TestCase):
    def setUp(self):
        self.feed_xml = (FIXTURES_DIR / "twitter_feed.xml").read_text()

    def write_sources_file(self, temp_dir):
        sources_path = Path(temp_dir) / "sources.yml"
        sources_path.write_text(
            "\n".join(
                [
                    "twitter:",
                    "  - handle: aaronjmars",
                    "    name: Aaron J. Mars",
                    "    verticals:",
                    "      - AI",
                    "      - Agents",
                    "    priority: high",
                    "    importance_score: 6",
                    "    feed_url: https://example.invalid/aaronjmars.xml",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return sources_path

    def test_manual_jsonl_ingestion_writes_normalized_twitter_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            sources_path = self.write_sources_file(temp_dir)
            output_dir = temp_dir / "out"
            manual_path = FIXTURES_DIR / "twitter_manual.jsonl"

            with patch.object(
                fetch_twitter.sys,
                "argv",
                [
                    "fetch_twitter.py",
                    str(manual_path),
                    "--sources-file",
                    str(sources_path),
                    "--output-dir",
                    str(output_dir),
                ],
            ):
                fetch_twitter.main()

            output_files = list(output_dir.glob("*.jsonl"))
            self.assertEqual(len(output_files), 1)

            records = read_jsonl(output_files[0])
            self.assertEqual(len(records), 2)
            self.assertTrue(all(record["source_type"] == "twitter" for record in records))

            first_record = records[0]
            expected_hash = fetch_twitter.compute_dedupe_hash("Manual JSONL fixture tweet one for AEON.")
            self.assertEqual(first_record["source_name"], "Aaron J. Mars")
            self.assertEqual(first_record["priority"], "high")
            self.assertEqual(first_record["importance_score"], 6)
            self.assertEqual(first_record["verticals"], ["AI", "Agents"])
            self.assertEqual(first_record["known_source"], "True")
            self.assertEqual(first_record["source_url"], "https://x.com/aaronjmars/status/tweet-1")
            self.assertEqual(first_record["dedupe_hash"], expected_hash)
            self.assertEqual(first_record["item_id"], expected_hash)

            second_record = records[1]
            second_expected_hash = fetch_twitter.compute_dedupe_hash(
                "Manual JSONL fixture tweet two for AEON ingestion."
            )
            self.assertEqual(second_record["dedupe_hash"], second_expected_hash)
            self.assertEqual(second_record["item_id"], second_expected_hash)

    def test_feed_ingestion_parses_fixture_and_applies_config_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            sources_path = self.write_sources_file(temp_dir)
            output_dir = temp_dir / "out"

            with patch.object(fetch_twitter, "fetch_feed_xml", return_value=self.feed_xml):
                with patch.object(
                    fetch_twitter.sys,
                    "argv",
                    [
                        "fetch_twitter.py",
                        "--feeds",
                        "--sources-file",
                        str(sources_path),
                        "--output-dir",
                        str(output_dir),
                    ],
                ):
                    fetch_twitter.main()

            output_files = list(output_dir.glob("*.jsonl"))
            self.assertEqual(len(output_files), 1)

            records = read_jsonl(output_files[0])
            self.assertEqual(len(records), 2)
            self.assertTrue(all(record["source_type"] == "twitter" for record in records))

            first_record = records[0]
            expected_hash = fetch_twitter.compute_dedupe_hash(
                "This is the first feed item body with more detail."
            )
            self.assertEqual(first_record["source_name"], "Aaron J. Mars")
            self.assertEqual(first_record["source_handle"], "aaronjmars")
            self.assertEqual(first_record["priority"], "high")
            self.assertEqual(first_record["importance_score"], 6)
            self.assertEqual(first_record["verticals"], ["AI", "Agents"])
            self.assertEqual(first_record["known_source"], "True")
            self.assertEqual(first_record["source_url"], "https://x.com/aaronjmars/status/1001")
            self.assertEqual(first_record["dedupe_hash"], expected_hash)
            self.assertEqual(first_record["item_id"], expected_hash)

            second_record = records[1]
            second_expected_hash = fetch_twitter.compute_dedupe_hash(
                "Second feed item title is longer than summary"
            )
            self.assertEqual(second_record["source_file"], "https://example.invalid/aaronjmars.xml")
            self.assertEqual(second_record["source_name"], "Aaron J. Mars")
            self.assertEqual(second_record["dedupe_hash"], second_expected_hash)
            self.assertEqual(second_record["item_id"], second_expected_hash)


if __name__ == "__main__":
    unittest.main()
