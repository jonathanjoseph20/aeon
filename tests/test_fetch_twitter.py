import importlib.util
import json
import io
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from email.message import Message
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


class FakeResponse:
    def __init__(self, body, status=200, content_type="application/atom+xml; charset=utf-8"):
        self._body = body.encode("utf-8")
        self.status = status
        self._headers = Message()
        self._headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    @property
    def headers(self):
        return self._headers


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

    def write_providers_file(self, temp_dir, default_provider="nitter"):
        providers_path = Path(temp_dir) / "providers.yml"
        providers_path.write_text(
            "\n".join(
                [
                    "twitter:",
                    f"  default_provider: {default_provider}",
                    "  providers:",
                    "    rsshub:",
                    "      type: rsshub",
                    "      url_template: https://rsshub.app/twitter/user/{handle}",
                    "    nitter:",
                    "      type: nitter",
                    "      url_template: https://nitter.net/{handle}/rss",
                    "    custom:",
                    "      type: custom",
                    "      url_template: https://example.invalid/twitter/{handle}.xml",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return providers_path

    def test_provider_url_generation_and_overrides(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            sources_path = temp_dir / "sources.yml"
            providers_path = self.write_providers_file(temp_dir, default_provider="nitter")
            sources_path.write_text(
                "\n".join(
                    [
                        "twitter:",
                        "  - source_name: X Profile",
                        "    source_type: twitter",
                        "    feed_url: https://x.com/0xngmi",
                        "  - source_name: Twitter Profile",
                        "    source_type: twitter",
                        "    feed_url: https://twitter.com/twngmi/",
                        "  - source_name: Custom Feed Override",
                        "    source_type: twitter",
                        "    handle: customfeed",
                        "    feed_url: https://example.invalid/custom.xml",
                        "  - source_name: Twitter Handle Wins",
                        "    source_type: twitter",
                        "    twitter_handle: winner",
                        "    feed_url: https://x.com/notwinner",
                        "    twitter_feed_provider: rsshub",
                        "  - source_name: sourceonly",
                        "    source_type: twitter",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            registry = fetch_twitter.load_twitter_sources(sources_path, providers_path)

            self.assertEqual(
                fetch_twitter.build_twitter_feed_url(
                    " @0xngmi ",
                    {"type": "rsshub", "url_template": "https://rsshub.app/twitter/user/{handle}"},
                ),
                "https://rsshub.app/twitter/user/0xngmi",
            )
            self.assertEqual(
                registry["0xngmi"]["feed_urls"],
                ["https://nitter.net/0xngmi/rss"],
            )
            self.assertEqual(
                registry["twngmi"]["feed_urls"],
                ["https://nitter.net/twngmi/rss"],
            )
            self.assertEqual(
                registry["customfeed"]["feed_urls"],
                ["https://example.invalid/custom.xml"],
            )
            self.assertEqual(
                registry["winner"]["feed_urls"],
                ["https://rsshub.app/twitter/user/winner"],
            )
            self.assertEqual(
                registry["sourceonly"]["feed_urls"],
                ["https://nitter.net/sourceonly/rss"],
            )

    def test_source_name_only_twitter_source_generates_default_provider_feed_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            sources_path = temp_dir / "sources.yml"
            providers_path = self.write_providers_file(temp_dir, default_provider="nitter")
            sources_path.write_text(
                "\n".join(
                    [
                        "twitter:",
                        "  - source_name: 0xngmi",
                        "    source_type: twitter",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            registry = fetch_twitter.load_twitter_sources(sources_path, providers_path)

            self.assertEqual(
                registry["0xngmi"]["source_name"],
                "0xngmi",
            )
            self.assertEqual(
                registry["0xngmi"]["feed_urls"],
                ["https://nitter.net/0xngmi/rss"],
            )

    def test_manual_jsonl_ingestion_writes_normalized_twitter_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            sources_path = self.write_sources_file(temp_dir)
            providers_path = self.write_providers_file(temp_dir, default_provider="nitter")
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
                    "--providers-file",
                    str(providers_path),
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
            providers_path = self.write_providers_file(temp_dir, default_provider="nitter")
            output_dir = temp_dir / "out"
            health_path = temp_dir / "metadata" / "source_health.jsonl"

            with patch.object(fetch_twitter, "fetch_feed_xml", return_value=self.feed_xml):
                with patch.object(
                    fetch_twitter.sys,
                    "argv",
                    [
                        "fetch_twitter.py",
                        "--feeds",
                        "--sources-file",
                        str(sources_path),
                        "--providers-file",
                        str(providers_path),
                        "--output-dir",
                        str(output_dir),
                        "--source-health-path",
                        str(health_path),
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

            health_records = read_jsonl(health_path)
            self.assertEqual(len(health_records), 1)
            self.assertEqual(health_records[0]["status"], "ok")
            self.assertEqual(health_records[0]["error_reason"], "")
            self.assertEqual(health_records[0]["provider"], "explicit")
            self.assertEqual(
                health_records[0]["generated_feed_url"],
                "https://example.invalid/aaronjmars.xml",
            )

    def test_feed_validation_writes_health_for_valid_html_and_malformed_responses(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            sources_path = temp_dir / "sources.yml"
            providers_path = self.write_providers_file(temp_dir, default_provider="nitter")
            output_dir = temp_dir / "out"
            health_path = temp_dir / "metadata" / "source_health.jsonl"

            sources_path.write_text(
                "\n".join(
                    [
                        "twitter:",
                        "  - handle: validfeed",
                        "    name: Valid Feed",
                        "    feed_url: https://x.com/validfeed",
                        "  - handle: htmlfeed",
                        "    name: HTML Feed",
                        "    feed_url: https://x.com/htmlfeed",
                        "  - handle: malformedfeed",
                        "    name: Broken Feed",
                        "    feed_url: https://x.com/malformedfeed",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            valid_feed = self.feed_xml
            html_feed = (FIXTURES_DIR / "twitter_feed_html.html").read_text(encoding="utf-8")
            malformed_feed = (FIXTURES_DIR / "twitter_feed_malformed.xml").read_text(encoding="utf-8")

            def fake_urlopen(request, timeout=20):
                url = request.full_url

                if url == "https://nitter.net/validfeed/rss":
                    return FakeResponse(valid_feed, content_type="application/atom+xml; charset=utf-8")

                if url == "https://nitter.net/htmlfeed/rss":
                    return FakeResponse(html_feed, content_type="text/html; charset=utf-8")

                if url == "https://nitter.net/malformedfeed/rss":
                    return FakeResponse(malformed_feed, content_type="application/xml; charset=utf-8")

                raise AssertionError(f"Unexpected URL: {url}")

            stdout = io.StringIO()

            with patch.object(fetch_twitter, "urlopen", side_effect=fake_urlopen):
                with patch.object(
                    fetch_twitter.sys,
                    "argv",
                    [
                        "fetch_twitter.py",
                        "--feeds",
                        "--sources-file",
                        str(sources_path),
                        "--providers-file",
                        str(providers_path),
                        "--output-dir",
                        str(output_dir),
                        "--source-health-path",
                        str(health_path),
                    ],
                ):
                    with redirect_stdout(stdout):
                        fetch_twitter.main()

            output = stdout.getvalue()
            self.assertIn("Twitter feeds: configured=3 fetched=1 failed=2 output_files=1", output)
            self.assertIn("html_response", output)
            self.assertIn("malformed_xml", output)

            output_files = list(output_dir.glob("*.jsonl"))
            self.assertEqual(len(output_files), 1)

            health_records = read_jsonl(health_path)
            self.assertEqual(len(health_records), 3)

            statuses = {record["source_name"]: record["status"] for record in health_records}
            reasons = {record["source_name"]: record["error_reason"] for record in health_records}

            self.assertEqual(statuses["Valid Feed"], "ok")
            self.assertEqual(statuses["HTML Feed"], "failed")
            self.assertEqual(statuses["Broken Feed"], "failed")
            self.assertEqual(reasons["Valid Feed"], "")
            self.assertEqual(reasons["HTML Feed"], "html_response")
            self.assertEqual(reasons["Broken Feed"], "malformed_xml")
            valid_health_record = next(record for record in health_records if record["source_name"] == "Valid Feed")
            self.assertEqual(valid_health_record["provider"], "nitter")
            self.assertEqual(
                valid_health_record["generated_feed_url"],
                "https://nitter.net/validfeed/rss",
            )


if __name__ == "__main__":
    unittest.main()
