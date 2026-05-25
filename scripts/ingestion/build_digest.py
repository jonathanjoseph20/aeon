import json
from collections import defaultdict
from datetime import datetime, UTC
from pathlib import Path

log_path = Path("data/processed/intake_log.jsonl")
digest_path = Path("data/processed/daily_digest.md")

digest_path.parent.mkdir(parents=True, exist_ok=True)


def get_item_id(item):
    return (
        item.get("id")
        or item.get("item_id")
        or item.get("hash")
        or "unknown"
    )


def get_source(item):
    return (
        item.get("source")
        or item.get("source_name")
        or "Unknown"
    )


def get_importance_score(item):
    try:
        return int(item.get("importance_score", 1))
    except (TypeError, ValueError):
        return 1


def get_signal_band(score):
    if score >= 8:
        return "High Signal"
    if score >= 4:
        return "Normal Digest"
    return "Low Priority"


with digest_path.open("w") as f:
    f.write("# Daily Intelligence Digest\n\n")
    f.write(
        f"Generated: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}\n\n"
    )

if not log_path.exists():
    with digest_path.open("a") as f:
        f.write("No intake log found.\n")
    raise SystemExit(0)

groups = defaultdict(list)
seen = set()

for line in log_path.read_text().splitlines():

    if not line.strip():
        continue

    item = json.loads(line)

    item_id = get_item_id(item)

    if item_id in seen:
        continue

    seen.add(item_id)

    verticals = item.get("verticals") or ["Unclassified"]
    primary_vertical = verticals[0] if verticals else "Unclassified"

    groups[primary_vertical].append(item)

with digest_path.open("a") as f:

    if not groups:
        f.write("No new classified items.\n")

    for vertical in sorted(groups):

        items = sorted(
            groups[vertical],
            key=get_importance_score,
            reverse=True
        )

        f.write(f"## {vertical}\n\n")

        for item in items[:10]:

            item_id = get_item_id(item)
            source = get_source(item)
            subject = item.get("subject", "(no subject)")
            priority = item.get("priority", "low")
            tags = ", ".join(item.get("verticals", []))
            preview = (
                item.get("summary")
                or item.get("content_preview", "")
            ).replace("\n", " ")

            importance_score = get_importance_score(item)
            signal_band = get_signal_band(importance_score)

            f.write(
                f"- `{item_id}` — **{source}** — {subject} — "
                f"*{signal_band} / {priority} / score {importance_score}* — "
                f"tags: {tags} — {preview[:180]}...\n"
            )

        f.write("\n")