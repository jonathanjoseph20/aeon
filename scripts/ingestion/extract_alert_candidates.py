import hashlib
import json
import re
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.source_config import is_enabled  # noqa: E402


log_path = Path("data/processed/intake_log.jsonl")
alert_path = Path("data/processed/alert_candidates.jsonl")

LOW_INFORMATION_TWEET_WORD_LIMIT = 18
GENERIC_MARKET_COMMENTARY_PATTERNS = (
    r"\bmarket wrap\b",
    r"\bmarket commentary\b",
    r"\bweekly market\b",
    r"\bwatching the tape\b",
    r"\bwatching markets\b",
    r"\bmarket feels\b",
    r"\brisk on\b",
    r"\brisk off\b",
    r"\bstocks? (are |is )?(higher|lower|mixed)\b",
    r"\bbonds? (are |is )?(higher|lower|mixed)\b",
    r"\bjust another day\b",
)
GENERIC_MARKET_COMMENTARY_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in GENERIC_MARKET_COMMENTARY_PATTERNS),
    re.IGNORECASE,
)


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_whitespace(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def build_narrative_signature(item):
    parts = [
        item.get("subject"),
        item.get("summary"),
        item.get("content_preview") or item.get("preview"),
        item.get("content"),
        item.get("raw_text"),
    ]
    cleaned = [normalize_whitespace(part).lower() for part in parts if normalize_whitespace(part)]

    if not cleaned:
        fallback_parts = [
            str(item.get("source_name") or "").lower(),
            str(item.get("source_url") or "").lower(),
        ]
        cleaned = [part for part in fallback_parts if part]

    return hashlib.sha256(" || ".join(cleaned).encode("utf-8")).hexdigest()[:16]


def build_alert_rank(item):
    importance_score = safe_int(item.get("importance_score"), 0)
    source_priority = str(item.get("priority") or "low").strip().lower()
    watchlist_hits = item.get("watchlist_hits") or []

    score = float(importance_score)
    reasons = []

    if importance_score >= 8:
        reasons.append("high_importance")

    if source_priority in {"high", "medium"}:
        score += 2 if source_priority == "high" else 1
        reasons.append(f"source_priority={source_priority}")

    if watchlist_hits:
        score += 3 + sum(safe_int(hit.get("score_boost"), 0) for hit in watchlist_hits)
        reasons.append("watchlist_hit")

    return round(score, 2), reasons


def should_suppress(item, narrative_signature, seen_narratives):
    if narrative_signature in seen_narratives:
        return "duplicate_narrative"

    item_text = normalize_whitespace(
        " ".join(
            part
            for part in (
                item.get("subject"),
                item.get("summary"),
                item.get("content_preview") or item.get("preview"),
                item.get("content"),
                item.get("raw_text"),
                item.get("source_name"),
            )
            if str(part or "").strip()
        )
    )

    if str(item.get("source_type") or "").strip().lower() == "twitter":
        word_count = len(re.findall(r"\b\w+\b", item_text))

        if (
            word_count < LOW_INFORMATION_TWEET_WORD_LIMIT
            and not item.get("watchlist_hits")
            and safe_int(item.get("importance_score"), 0) < 8
        ):
            return "low_information_tweet"

    if (
        not item.get("watchlist_hits")
        and safe_int(item.get("importance_score"), 0) < 8
        and GENERIC_MARKET_COMMENTARY_RE.search(item_text)
    ):
        return "generic_market_commentary"

    return ""


if not log_path.exists():
    print("No intake log found.")
    raise SystemExit(0)

alerts = []
seen_narratives = set()

for line in log_path.read_text().splitlines():
    if not line.strip():
        continue

    item = json.loads(line)

    if not is_enabled(item, "alert_enabled", True):
        continue

    importance_score = safe_int(item.get("importance_score"), 1)
    watchlist_hits = item.get("watchlist_hits", [])

    if importance_score < 8 and not watchlist_hits:
        continue

    narrative_signature = build_narrative_signature(item)
    suppression_reason = should_suppress(item, narrative_signature, seen_narratives)

    if suppression_reason:
        continue

    seen_narratives.add(narrative_signature)
    alert_rank_score, alert_rank_reasons = build_alert_rank(item)
    enriched_item = dict(item)
    enriched_item["alert_rank_score"] = alert_rank_score
    enriched_item["alert_rank_reasons"] = alert_rank_reasons
    alerts.append(enriched_item)

alerts = sorted(
    alerts,
    key=lambda item: (
        -safe_int(item.get("alert_rank_score"), 0),
        -safe_int(item.get("importance_score"), 0),
        str(item.get("timestamp") or ""),
        str(item.get("item_id") or ""),
    ),
)

alert_path.parent.mkdir(parents=True, exist_ok=True)

with alert_path.open("w") as f:
    for item in alerts:
        f.write(json.dumps(item) + "\n")

print(f"Extracted {len(alerts)} alert candidates.")
