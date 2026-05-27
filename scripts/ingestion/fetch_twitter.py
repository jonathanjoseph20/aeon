import argparse
import hashlib
import json
import sys
import re
from datetime import datetime, UTC
from pathlib import Path
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.source_config import (
    build_twitter_feed_url,
    load_source_entries,
    normalize_handle,
    normalize_twitter_handle,
    normalize_source_type,
)

DEFAULT_SOURCE_HEALTH_PATH = Path("data/metadata/source_health.jsonl")
VALID_FEED_ROOT_NAMES = {"feed", "rss", "rdf"}


def safe_int(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def compute_dedupe_hash(text):
    normalized_content = str(text or "").lower().strip()
    return hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()[:16]


def collect_inputs(inputs):
    files = []

    for raw_input in inputs:
        path = Path(raw_input)

        if path.is_dir():
            files.extend(sorted(path.glob("*.jsonl")))
        elif path.suffix.lower() == ".jsonl":
            files.append(path)

    return files


def load_twitter_sources(
    sources_path=Path("config/sources.yml"),
    providers_path=Path("config/providers.yml"),
):
    source_entries = load_source_entries(Path(sources_path), Path(providers_path))
    registry = {}

    for entry in source_entries:
        source_type = normalize_source_type(entry.get("source_type"))

        if source_type != "twitter" and not entry.get("feed_urls"):
            continue

        handle = normalize_twitter_handle(entry)

        if not handle:
            continue

        registry[handle] = {
            "source_name": entry.get("source_name") or entry.get("name") or entry.get("handle") or "Unknown",
            "source_type": source_type or "twitter",
            "priority": entry.get("priority", "low"),
            "importance_score": safe_int(entry.get("importance_score", 1)),
            "default_verticals": entry.get("default_verticals", []) or [],
            "verticals": entry.get("default_verticals", []) or entry.get("verticals", []) or [],
            "feed_urls": entry.get("feed_urls", []) or [],
            "feed_provider": entry.get("feed_provider") or entry.get("twitter_feed_provider") or "explicit",
            "generated_feed_url": entry.get("generated_feed_url") or entry.get("feed_url") or "",
            "watchlist_boost": safe_int(entry.get("watchlist_boost"), 0),
            "promotion_threshold_override": entry.get("promotion_threshold_override"),
            "digest_enabled": entry.get("digest_enabled", True),
            "alert_enabled": entry.get("alert_enabled", True),
        }

    return registry


def local_name(tag):
    return str(tag or "").rsplit("}", 1)[-1].lower()


def clean_text(value):
    text = unescape(str(value or ""))
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_content_type(headers):
    if not headers:
        return ""

    content_type = ""

    if hasattr(headers, "get_content_type"):
        try:
            content_type = headers.get_content_type() or ""
        except Exception:
            content_type = ""

    if not content_type and hasattr(headers, "get"):
        content_type = headers.get("Content-Type", "") or headers.get("content-type", "")

    return str(content_type or "").split(";", 1)[0].strip().lower()


def looks_like_html(feed_xml):
    sample = str(feed_xml or "").lstrip().lower()[:800]

    if not sample:
        return False

    return (
        sample.startswith("<!doctype html")
        or sample.startswith("<html")
        or "<html" in sample
        or "<body" in sample
        or "<head" in sample
    )


def diagnose_feed_xml(feed_xml, status=None, content_type=""):
    if status is not None:
        try:
            if int(status) >= 400:
                return f"http_status_{int(status)}"
        except (TypeError, ValueError):
            pass

    normalized_type = str(content_type or "").strip().lower()

    if normalized_type in {"text/html", "application/xhtml+xml"}:
        return "html_response"

    if looks_like_html(feed_xml):
        return "html_response"

    body = str(feed_xml or "").strip()

    if not body:
        return "empty_response"

    try:
        root = ET.fromstring(feed_xml)
    except ET.ParseError:
        return "malformed_xml"

    root_name = local_name(root.tag)

    if root_name not in VALID_FEED_ROOT_NAMES:
        return f"unsupported_format_{root_name}"

    return ""


class FeedValidationError(Exception):
    def __init__(self, feed_url, error_reason, status=None, content_type=""):
        super().__init__(error_reason)
        self.feed_url = feed_url
        self.error_reason = error_reason
        self.status = status
        self.content_type = content_type


def first_xml_text(element, names):
    for node in element.iter():
        if local_name(node.tag) in names:
            text = clean_text("".join(node.itertext()))
            if text:
                return text

    return ""


def first_atom_link(entry):
    for node in entry.iter():
        if local_name(node.tag) != "link":
            continue

        href = str(node.attrib.get("href", "") or "").strip()

        if not href:
            continue

        rel = str(node.attrib.get("rel", "") or "").strip().lower()

        if rel in ("", "alternate"):
            return href

    for node in entry.iter():
        if local_name(node.tag) == "link":
            href = str(node.attrib.get("href", "") or "").strip()
            if href:
                return href

    return ""


def extract_feed_items(feed_xml, feed_url):
    root = ET.fromstring(feed_xml)
    root_name = local_name(root.tag)
    items = []

    if root_name == "feed":
        entry_nodes = [node for node in root.iter() if local_name(node.tag) == "entry"]

        for entry in entry_nodes:
            title = first_xml_text(entry, ["title"])
            summary = first_xml_text(entry, ["summary"])
            content = first_xml_text(entry, ["content"])
            link = first_atom_link(entry)
            published = first_xml_text(entry, ["published", "updated"])
            item_id = first_xml_text(entry, ["id"]) or link or title or feed_url
            text = max((title, summary, content), key=len, default="")
            text = clean_text(text or title or summary or content)

            items.append(
                {
                    "id": item_id,
                    "tweet_id": item_id,
                    "status_id": item_id,
                    "id_str": item_id,
                    "text": text,
                    "full_text": text,
                    "content": text,
                    "body": text,
                    "tweet_text": text,
                    "message": text,
                    "url": link or feed_url,
                    "tweet_url": link or feed_url,
                    "source_url": link or feed_url,
                    "created_at": published,
                    "posted_at": published,
                    "timestamp": published
                }
            )

        return items

    item_nodes = [node for node in root.iter() if local_name(node.tag) == "item"]

    for item in item_nodes:
        title = first_xml_text(item, ["title"])
        description = first_xml_text(item, ["description", "encoded", "summary", "content"])
        link = first_xml_text(item, ["link"])
        published = first_xml_text(item, ["pubdate", "published", "updated", "date"])
        item_id = first_xml_text(item, ["guid", "id"]) or link or title or feed_url
        text = max((title, description), key=len, default="")
        text = clean_text(text or title or description)

        items.append(
            {
                "id": item_id,
                "tweet_id": item_id,
                "status_id": item_id,
                "id_str": item_id,
                "text": text,
                "full_text": text,
                "content": text,
                "body": text,
                "tweet_text": text,
                "message": text,
                "url": link or feed_url,
                "tweet_url": link or feed_url,
                "source_url": link or feed_url,
                "created_at": published,
                "posted_at": published,
                "timestamp": published
            }
        )

    return items


def fetch_feed_xml(feed_url, timeout=20):
    request = Request(
        feed_url,
        headers={
            "User-Agent": "AEON feed ingestion/1.0"
        }
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            content_type = normalize_content_type(getattr(response, "headers", None))
            charset = ""

            if getattr(response, "headers", None) and hasattr(response.headers, "get_content_charset"):
                try:
                    charset = response.headers.get_content_charset() or ""
                except Exception:
                    charset = ""

            feed_xml = response.read().decode(charset or "utf-8", errors="replace")
    except HTTPError as exc:
        status = getattr(exc, "code", None)
        content_type = normalize_content_type(getattr(exc, "headers", None))
        raise FeedValidationError(
            feed_url=feed_url,
            error_reason=f"http_status_{status}" if status is not None else "http_error",
            status=status,
            content_type=content_type,
        ) from exc
    except URLError as exc:
        raise FeedValidationError(
            feed_url=feed_url,
            error_reason="url_error",
        ) from exc

    error_reason = diagnose_feed_xml(feed_xml, status=status, content_type=content_type)

    if error_reason:
        raise FeedValidationError(
            feed_url=feed_url,
            error_reason=error_reason,
            status=status,
            content_type=content_type,
        )

    return feed_xml


def get_first(record, keys):
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return ""


def extract_handle(record):
    if isinstance(record.get("user"), dict):
        nested = record["user"]
        handle = get_first(
            nested,
            ["screen_name", "username", "handle", "name"]
        )

        if handle:
            return handle

    return get_first(
        record,
        [
            "source_handle",
            "author_handle",
            "handle",
            "username",
            "screen_name",
            "user_handle",
            "author"
        ]
    )


def extract_text(record):
    return get_first(
        record,
        ["text", "full_text", "content", "body", "tweet_text", "message"]
    )


def build_record(raw_record, source_file, twitter_sources):
    text = str(extract_text(raw_record) or "").strip()

    if not text:
        return None

    handle = normalize_handle(extract_handle(raw_record))
    source_meta = twitter_sources.get(handle, {})
    tweet_id = str(
        get_first(
            raw_record,
            ["id", "tweet_id", "status_id", "tweetId", "id_str"]
        )
    ).strip()

    source_name = (
        raw_record.get("source_name")
        or source_meta.get("source_name")
        or handle
        or Path(source_file).stem
        or "twitter"
    )
    priority = raw_record.get("priority") or source_meta.get("priority", "low")
    importance_score = safe_int(
        raw_record.get("importance_score"),
        source_meta.get("importance_score", 1)
    )
    verticals = raw_record.get("verticals") or source_meta.get("default_verticals") or source_meta.get("verticals", [])
    subject = raw_record.get("subject") or text[:120]
    source_url = get_first(raw_record, ["url", "tweet_url", "source_url"])
    source_file_value = raw_record.get("source_file") or str(source_file)

    if not source_url and handle and tweet_id:
        source_url = f"https://x.com/{handle}/status/{tweet_id}"

    dedupe_hash = compute_dedupe_hash(text)

    return {
        "source_type": "twitter",
        "source_file": str(source_file_value),
        "source_id": tweet_id or source_url or handle or source_file,
        "source_name": source_name,
        "source_handle": handle,
        "source_url": source_url,
        "source_domain": "x.com" if handle else "",
        "known_source": "True" if handle in twitter_sources else "False",
        "subject": subject,
        "priority": priority,
        "importance_score": importance_score,
        "verticals": verticals,
        "content": text,
        "content_preview": text[:400],
        "created_at": get_first(raw_record, ["created_at", "posted_at", "timestamp"]),
        "dedupe_hash": dedupe_hash,
        "item_id": dedupe_hash,
        "timestamp": datetime.now(UTC).isoformat(),
        "raw_text": text
    }


def normalize_feed_record(feed_record, feed_url, handle, source_meta):
    handle = normalize_handle(handle)
    text = str(feed_record.get("text") or "").strip()

    if not text:
        return None

    return {
        "source_handle": handle,
        "source_name": feed_record.get("source_name") or source_meta.get("source_name") or handle or feed_url,
        "source_type": "twitter",
        "priority": feed_record.get("priority") or source_meta.get("priority", "low"),
        "importance_score": safe_int(
            feed_record.get("importance_score"),
            source_meta.get("importance_score", 1)
        ),
        "verticals": feed_record.get("verticals") or source_meta.get("default_verticals") or source_meta.get("verticals", []),
        "default_verticals": source_meta.get("default_verticals", []),
        "watchlist_boost": safe_int(source_meta.get("watchlist_boost"), 0),
        "promotion_threshold_override": source_meta.get("promotion_threshold_override"),
        "digest_enabled": source_meta.get("digest_enabled", True),
        "alert_enabled": source_meta.get("alert_enabled", True),
        "source_file": feed_url,
        "source_url": feed_record.get("source_url") or feed_url,
        "source_domain": "x.com" if handle else "",
        "known_source": "True" if source_meta else "False",
        "subject": feed_record.get("subject") or text[:120],
        "text": text,
        "full_text": text,
        "content": text,
        "body": text,
        "tweet_text": text,
        "message": text,
        "url": feed_record.get("url") or feed_record.get("source_url") or feed_url,
        "tweet_url": feed_record.get("tweet_url") or feed_record.get("source_url") or feed_url,
        "created_at": feed_record.get("created_at") or feed_record.get("posted_at") or feed_record.get("timestamp"),
        "tweet_id": feed_record.get("tweet_id") or feed_record.get("id") or feed_record.get("id_str") or feed_record.get("source_url") or feed_url,
        "status_id": feed_record.get("status_id") or feed_record.get("tweet_id") or feed_record.get("id") or feed_record.get("source_url") or feed_url,
        "id": feed_record.get("id") or feed_record.get("tweet_id") or feed_record.get("status_id") or feed_record.get("source_url") or feed_url,
        "id_str": feed_record.get("id_str") or feed_record.get("id") or feed_record.get("tweet_id") or feed_record.get("source_url") or feed_url
    }


def build_feed_records(feed_url, handle, source_meta, twitter_sources):
    checked_at = datetime.now(UTC).isoformat()
    source_name = source_meta.get("source_name") or handle or feed_url
    provider = source_meta.get("feed_provider") or "explicit"
    health_record = {
        "source_name": source_name,
        "source_type": "twitter",
        "feed_url": feed_url,
        "provider": provider,
        "generated_feed_url": feed_url,
        "status": "ok",
        "error_reason": "",
        "checked_at": checked_at,
    }

    try:
        feed_xml = fetch_feed_xml(feed_url)
        parsed_records = extract_feed_items(feed_xml, feed_url)
    except FeedValidationError as exc:
        health_record["status"] = "failed"
        health_record["error_reason"] = exc.error_reason
        return [], health_record
    except ET.ParseError:
        health_record["status"] = "failed"
        health_record["error_reason"] = "malformed_xml"
        return [], health_record

    records = []

    for parsed_record in parsed_records:
        record = normalize_feed_record(parsed_record, feed_url, handle, source_meta)

        if not record:
            continue

        built = build_record(record, feed_url, twitter_sources)

        if built:
            records.append(built)

    return records, health_record


def safe_file_stem(value):
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", normalize_handle(value) or str(value or "").lower().strip())
    cleaned = cleaned.strip("-._")
    return cleaned or "twitter"


def write_records(output_path, records):
    with Path(output_path).open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Normalize manual Twitter JSONL exports and configured RSS/Atom feeds into AEON intake records."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="One or more JSONL files or directories containing JSONL files."
    )
    parser.add_argument(
        "--output-dir",
        default="data/intake/twitter",
        help="Directory where normalized JSONL files will be written."
    )
    parser.add_argument(
        "--source-name",
        default="",
        help="Optional source name override for records without a configured handle."
    )
    parser.add_argument(
        "--priority",
        default="low",
        choices=["low", "medium", "high"],
        help="Fallback priority when the source is not configured."
    )
    parser.add_argument(
        "--importance-score",
        default=1,
        help="Fallback importance score when the source is not configured."
    )
    parser.add_argument(
        "--sources-file",
        default="config/sources.yml",
        help="YAML file containing Twitter/X source metadata and optional feed URLs."
    )
    parser.add_argument(
        "--providers-file",
        default="config/providers.yml",
        help="YAML file containing Twitter feed provider templates and defaults."
    )
    parser.add_argument(
        "--feeds",
        action="store_true",
        help="Fetch configured RSS/Atom feed URLs from config/sources.yml."
    )
    parser.add_argument(
        "--source-health-path",
        default=str(DEFAULT_SOURCE_HEALTH_PATH),
        help="JSONL file where Twitter feed health checks are written."
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_health_path = Path(args.source_health_path)

    twitter_sources = load_twitter_sources(args.sources_file, args.providers_file)
    input_files = collect_inputs(args.inputs)
    wrote_anything = False
    feed_output_files = 0
    feed_successes = 0
    feed_failures = 0
    health_records = []

    if not input_files and not args.feeds:
        parser.error("provide one or more JSONL inputs, or pass --feeds")

    for input_file in input_files:
        records = []

        for line in Path(input_file).read_text().splitlines():
            if not line.strip():
                continue

            raw_record = json.loads(line)

            if not isinstance(raw_record, dict):
                continue

            record = build_record(raw_record, input_file, twitter_sources)

            if not record:
                continue

            if args.source_name and not record["source_handle"]:
                record["source_name"] = args.source_name

            if record["priority"] == "low" and args.priority:
                record["priority"] = args.priority

            if record["importance_score"] == 1 and args.importance_score:
                record["importance_score"] = safe_int(args.importance_score, 1)

            records.append(record)

        if not records:
            print(f"Skipped empty JSONL: {input_file}")
            continue

        output_name = (
            f"{Path(input_file).stem}-"
            f"{hashlib.sha256(str(Path(input_file).resolve()).encode('utf-8')).hexdigest()[:10]}.jsonl"
        )
        output_path = output_dir / output_name

        write_records(output_path, records)

        print(f"Wrote: {output_path}")
        wrote_anything = True

    if args.feeds:
        configured_feeds = []

        for handle, meta in twitter_sources.items():
            for feed_url in meta.get("feed_urls", []):
                configured_feeds.append((handle, feed_url, meta))

        configured_feeds.sort(key=lambda item: (item[0], item[1]))
        total_feeds = len(configured_feeds)

        if not configured_feeds:
            print("No Twitter feed URLs were configured.")
        else:
            for handle, feed_url, meta in configured_feeds:
                records, health_record = build_feed_records(feed_url, handle, meta, twitter_sources)
                health_records.append(health_record)

                if health_record["status"] != "ok":
                    feed_failures += 1
                    print(
                        f"Skipped feed for {handle or feed_url}: "
                        f"{health_record['error_reason']}"
                    )
                    continue

                feed_successes += 1

                if not records:
                    continue

                output_name = (
                    f"{safe_file_stem(handle)}-feed-"
                    f"{hashlib.sha256(feed_url.encode('utf-8')).hexdigest()[:10]}-"
                    f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.jsonl"
                )
                output_path = output_dir / output_name

                write_records(output_path, records)
                feed_output_files += 1
                wrote_anything = True

        source_health_path.parent.mkdir(parents=True, exist_ok=True)
        write_records(source_health_path, health_records)
        print(
            f"Twitter feeds: configured={total_feeds} "
            f"fetched={feed_successes} failed={feed_failures} "
            f"output_files={feed_output_files}"
        )

    if not wrote_anything and not args.feeds:
        print("No Twitter items were written.")


if __name__ == "__main__":
    main()
