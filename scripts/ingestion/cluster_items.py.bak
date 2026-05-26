import json
import hashlib
from collections import defaultdict
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
    "will", "their", "they", "been"
}

KEYWORD_MIN_LENGTH = 4

clusters = defaultdict(list)


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


for line in log_path.read_text().splitlines():

    if not line.strip():
        continue

    item = json.loads(line)

    subject = item.get("subject", "")
    summary = item.get("summary", "")

    combined = f"{subject} {summary}"

    keywords = extract_keywords(combined)

    if not keywords:
        continue

    topic_fingerprint = hashlib.sha256(
        " ".join(keywords[:8]).encode("utf-8")
    ).hexdigest()[:12]

    item["cluster_keywords"] = keywords[:10]
    item["topic_fingerprint"] = topic_fingerprint

    clusters[topic_fingerprint].append(item)

with cluster_path.open("w") as f:

    for fingerprint, items in clusters.items():

        cluster = {
            "topic_fingerprint": fingerprint,
            "cluster_size": len(items),
            "keywords": items[0]["cluster_keywords"],
            "items": [
                {
                    "source": item.get("source_name"),
                    "subject": item.get("subject"),
                    "verticals": item.get("verticals"),
                    "importance_score": item.get(
                        "importance_score"
                    )
                }
                for item in items
            ]
        }

        f.write(json.dumps(cluster) + "\n")

print(f"Generated {len(clusters)} topic clusters.")