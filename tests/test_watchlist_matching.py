import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "classify_email.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_classify_email_module():
    spec = importlib.util.spec_from_file_location("classify_email", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


classify_email = load_classify_email_module()


def read_jsonl_record(path):
    lines = [line for line in Path(path).read_text().splitlines() if line.strip()]
    assert lines
    return json.loads(lines[0])


class WatchlistMatchingTests(unittest.TestCase):
    def test_base_watchlist_ignores_ordinary_usage_but_matches_precise_base_contexts(self):
        false_positive_item = read_jsonl_record(FIXTURES_DIR / "watchlist_base_false_positive.jsonl")
        positive_item = read_jsonl_record(FIXTURES_DIR / "watchlist_base_positive.jsonl")

        watchlist = {
            "entities": {
                "Base": {
                    "phrase_match": ["model routing"],
                    "token_match": ["coinbase"],
                    "regex_match": [r"\bBase\b\s+ecosystem"],
                    "verticals": ["DeFi", "Portfolio"],
                    "score_boost": 4,
                }
            }
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            source_entries_path = temp_dir / "sources.yml"
            source_entries_path.write_text("sources: []\n", encoding="utf-8")
            source_entries = classify_email.load_source_entries(source_entries_path)

            false_positive_record = classify_email.classify_item(
                false_positive_item,
                email_registry={},
                twitter_registry={},
                verticals={},
                watchlist=watchlist,
                seen=set(),
                source_entries=source_entries,
            )
            positive_record = classify_email.classify_item(
                positive_item,
                email_registry={},
                twitter_registry={},
                verticals={},
                watchlist=watchlist,
                seen=set(),
                source_entries=source_entries,
            )

        self.assertIsNotNone(false_positive_record)
        self.assertEqual(false_positive_record["watchlist_hits"], [])

        self.assertIsNotNone(positive_record)
        self.assertEqual(len(positive_record["watchlist_hits"]), 1)
        self.assertEqual(positive_record["watchlist_hits"][0]["entity"], "Base")
        self.assertCountEqual(
            positive_record["watchlist_hits"][0]["matched_keywords"],
            ["model routing", "coinbase", r"\bBase\b\s+ecosystem"],
        )


if __name__ == "__main__":
    unittest.main()
