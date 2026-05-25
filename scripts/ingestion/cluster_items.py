import json
import hashlib
from pathlib import Path

log_path = Path("data/processed/intake_log.jsonl")
cluster_path = Path("data/processed/topic_clusters.jsonl")

if not log_path.exists():
    print("No intake log found.")
    raise SystemExit(0)

STOPWORDS = {
    "the", "and", "for", "with", "that",
    "this", "from", "your", "about",
    "into", "what", "welcome", "have",
    "will", "their", "they", "been",
    "you", "our", "are", "was", "were",
    "can", "has", "had", "but", "not",
    "all", "more", "new", "today",
    "email", "newsletter", "read"
}

KEYWORD_MIN_LENGTH = 4
MIN_SHARED_KEYWORDS = 3


def extract_keywords(text):

    tokens = []

    for word in text.lower().split():

        cleaned = "".join(
            c for c in word if c.isalnum()
        )

        if len(cleaned) < KEYWORD_MIN_LENGTH:
            continue

        if cleaned in STOPWORDS:
            continue

        tokens.append(cleaned)

    return sorted(set(tokens))


def get_item_id(item):
    return (
        item.get("id")
        or item.get("item_id")
        or item.get("hash")
        or "unknown"
    )


def item_text(item):
    subject = item.get("subject", "")
    summary = item.get("summary", "")
    preview = item.get("content_preview", "")

    return f"{subject} {summary} {preview}"


items = []

for line in log_path.read_text().splitlines():

    if not line.strip():
        continue

    item = json.loads(line)
    keywords = extract_keywords(item_text(item))

    if not keywords:
        continue

    item["cluster_keywords"] = keywords[:15]

    items.append(item)

clusters = []

for item in items:

    item_keywords = set(item["cluster_keywords"])
    matched_cluster = None
    best_overlap = 0

    for cluster in clusters:

        cluster_keywords = set(cluster["keywords"])
        overlap = len(item_keywords.intersection(cluster_keywords))

        if overlap > best_overlap:
            best_overlap = overlap
            matched_cluster = cluster

    if matched_cluster and best_overlap >= MIN_SHARED_KEYWORDS:

        matched_cluster["items"].append(item)

        merged_keywords = sorted(
            set(matched_cluster["keywords"]).union(item_keywords)
        )

        matched_cluster["keywords"] = merged_keywords[:20]

    else:

        seed = " ".join(item["cluster_keywords"][:8])
        fingerprint = hashlib.sha256(
            seed.encode("utf-8")
        ).hexdigest()[:12]

        clusters.append(
            {
                "topic_fingerprint": fingerprint,
                "keywords": item["cluster_keywords"],
                "items": [item]
            }
        )

with cluster_path.open("w") as f:

    for cluster in clusters:

        cluster_items = cluster["items"]

        record = {
            "topic_fingerprint": cluster["topic_fingerprint"],
            "cluster_size": len(cluster_items),
            "keywords": cluster["keywords"][:12],
            "items": [
                {
                    "item_id": get_item_id(item),
                    "source": item.get("source_name"),
                    "subject": item.get("subject"),
                    "verticals": item.get("verticals"),
                    "importance_score": item.get("importance_score")
                }
                for item in cluster_items
            ]
        }

        f.write(json.dumps(record) + "\n")

print(f"Generated {len(clusters)} topic clusters.")