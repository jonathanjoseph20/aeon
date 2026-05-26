import yaml
import json
import hashlib
from pathlib import Path
from datetime import datetime, UTC

IGNORE_SUBJECT_PATTERNS = [
    "welcome",
    "complete your sign up",
    "confirm your email",
    "verify your email",
    "activate your account",
    "thanks for subscribing",
    "please confirm",
    "confirm subscription",
    "complete your signup"
]

GMAIL_LABEL_VERTICAL_PRIORS = {
    "Research/AI": ["AI"],
    "Research/RWA_Tokenization": ["RWA"],
    "Research/PrivateMarkets": ["RWA"],
    "Research/Macro": ["Macro"],
    "Research/Portfolio_Assets": ["Portfolio"],
    "Research/DeFi": ["DeFi"],
    "Research/Personal": ["Personal"]
}

with open("config/verticals.yml", "r") as f:
    verticals = yaml.safe_load(f)

watchlist_path = Path("config/watchlist.yml")
if watchlist_path.exists():
    with watchlist_path.open("r") as f:
        watchlist = yaml.safe_load(f) or {}
else:
    watchlist = {}

email_folder = Path("data/intake/email")
log_path = Path("data/processed/intake_log.jsonl")

log_path.parent.mkdir(parents=True, exist_ok=True)
log_path.touch(exist_ok=True)

existing_ids = set()

with open(log_path, "r") as f:
    for line in f:
        if line.strip():
            existing_ids.add(json.loads(line).get("item_id"))

files = sorted(email_folder.glob("*.txt"))

for email_path in files:

    raw_content = email_path.read_text()

    metadata = {
        "source_name": "Unknown",
        "source_domain": "",
        "known_source": "",
        "sender": "",
        "subject": "",
        "priority": "low",
        "importance_score": 1,
        "gmail_label": ""
    }

    body_lines = []

    for line in raw_content.splitlines():

        line = line.strip()

        if not line:
            continue

        if line.startswith("SOURCE:"):
            metadata["source_name"] = line.replace("SOURCE:", "").strip()

        elif line.startswith("SOURCE_DOMAIN:"):
            metadata["source_domain"] = line.replace("SOURCE_DOMAIN:", "").strip()

        elif line.startswith("KNOWN_SOURCE:"):
            metadata["known_source"] = line.replace("KNOWN_SOURCE:", "").strip()

        elif line.startswith("SENDER:"):
            metadata["sender"] = line.replace("SENDER:", "").strip()

        elif line.startswith("SUBJECT:"):
            metadata["subject"] = line.replace("SUBJECT:", "").strip()

        elif line.startswith("PRIORITY:"):
            metadata["priority"] = line.replace("PRIORITY:", "").strip()

        elif line.startswith("GMAIL_LABEL:"):
            metadata["gmail_label"] = line.replace("GMAIL_LABEL:", "").strip()

        elif line.startswith("IMPORTANCE_SCORE:"):
            metadata["importance_score"] = int(
                line.replace("IMPORTANCE_SCORE:", "").strip()
            )

        else:
            body_lines.append(line)

    subject_lower = metadata["subject"].lower()

    if any(pattern in subject_lower for pattern in IGNORE_SUBJECT_PATTERNS):
        print(f"Ignored noise: {email_path.name} — {metadata['subject']}")
        continue

    content = " ".join(body_lines).strip()
    normalized = content.lower()
    searchable_text = f"{metadata['subject']} {content}".lower()

    item_id = hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()[:16]

    if item_id in existing_ids:
        print(f"Skipped duplicate: {email_path.name}")
        continue

    scores = {}

    for vertical, data in verticals.items():

        keywords = data.get("keywords", [])
        score = 0

        for keyword in keywords:
            score += normalized.count(keyword.lower())

        scores[vertical] = score

    label_verticals = GMAIL_LABEL_VERTICAL_PRIORS.get(
        metadata["gmail_label"],
        []
    )

    for vertical in label_verticals:
        scores[vertical] = scores.get(vertical, 0) + 3

    if metadata["known_source"] == "True":
        for vertical in label_verticals:
            scores[vertical] = scores.get(vertical, 0) + 1

    watchlist_hits = []

    for entity_name, entity_data in watchlist.get("entities", {}).items():

        keywords = entity_data.get("keywords", [])
        entity_verticals = entity_data.get("verticals", [])
        score_boost = int(entity_data.get("score_boost", 0))

        matched_keywords = [
            keyword for keyword in keywords
            if keyword.lower() in searchable_text
        ]

        if not matched_keywords:
            continue

        watchlist_hits.append({
            "entity": entity_name,
            "matched_keywords": matched_keywords,
            "score_boost": score_boost
        })

        for vertical in entity_verticals:
            scores[vertical] = scores.get(vertical, 0) + score_boost

        metadata["importance_score"] += score_boost

        if metadata["importance_score"] >= 8:
            metadata["priority"] = "high"
        elif metadata["importance_score"] >= 4:
            metadata["priority"] = "medium"

    matched_verticals = [
        vertical for vertical, score in scores.items()
        if score >= 2
    ]

    record = {
        "item_id": item_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "source_type": "email_manual",
        "source_file": str(email_path),
        "source_name": metadata["source_name"],
        "source_domain": metadata["source_domain"],
        "known_source": metadata["known_source"],
        "sender": metadata["sender"],
        "subject": metadata["subject"],
        "priority": metadata["priority"],
        "importance_score": metadata["importance_score"],
        "gmail_label": metadata["gmail_label"],
        "verticals": matched_verticals,
        "scores": scores,
        "watchlist_hits": watchlist_hits,
        "content_preview": content[:200]
    }

    with open(log_path, "a") as f:
        f.write(json.dumps(record) + "\n")

    print(f"Processed: {email_path.name} → {matched_verticals}")