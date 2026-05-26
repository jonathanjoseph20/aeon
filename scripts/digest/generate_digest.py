import json
import re
from collections import defaultdict
from pathlib import Path

log_path = Path("data/processed/intake_log.jsonl")
output_path = Path("data/processed/daily_digest.md")

vertical_map = defaultdict(list)

with open(log_path, "r") as f:
    for line in f:
        if not line.strip():
            continue

        item = json.loads(line)

        for vertical in item.get("verticals", []):
            vertical_map[vertical].append(item)

lines = []
lines.append("# Daily Intelligence Digest\n")

for vertical, items in sorted(vertical_map.items()):
    items = sorted(
        items,
        key=lambda x: x.get("importance_score", 1),
        reverse=True
    )

    lines.append(f"\n## {vertical}\n")

    for item in items[-5:]:

        preview = item["content_preview"].replace("\n", " ").strip()

        preview = re.sub(r"https?://\S+", "", preview)
        preview = re.sub(r"\s+", " ", preview).strip()

        source = (
            item.get("source_name")
            or item.get("source_handle")
            or item.get("author_handle")
            or item["source_file"]
        )
        subject = item.get("subject", "")
        priority = item.get("priority", "low")
        item_id = item.get("item_id", "no-id")

        lines.append(
            f"- `{item_id}` — **{source}** — {subject} — *{priority}* — {preview[:180]}..."
        )

digest = "\n".join(lines)

output_path.write_text(digest)

print(digest)
print(f"\nSaved digest to: {output_path}")
