import json
from collections import defaultdict
from datetime import datetime, UTC
from pathlib import Path

log_path = Path("data/processed/intake_log.jsonl")
digest_path = Path("data/processed/daily_digest.md")

digest_path.parent.mkdir(parents=True, exist_ok=True)

with digest_path.open("w") as f:
    f.write("# Daily Intelligence Digest\n\n")
    f.write(f"Generated: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}\n\n")

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

    item_id = (
        item.get("id")
        or item.get("item_id")
        or item.get("hash")
        or "unknown"
    )

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
        f.write(f"## {vertical}\n\n")

        for item in groups[vertical][:10]:
            item_id = (
                item.get("id")
                or item.get("item_id")
                or item.get("hash")
                or "unknown"
            )

            source = (
                item.get("source")
                or item.get("source_name")
                or "Unknown"
            )

            subject = item.get("subject", "(no subject)")
            priority = item.get("priority", "low")
            tags = ", ".join(item.get("verticals", []))
            preview = item.get("content_preview", "").replace("\n", " ")

            f.write(
                f"- `{item_id}` — **{source}** — {subject} — "
                f"*{priority}* — tags: {tags} — {preview[:180]}...\n"
            )

        f.write("\n")
