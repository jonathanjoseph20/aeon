import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import sys

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ingestion.build_entity_summary import build_entity_summary


LOG_PATH = Path("data/processed/intake_log.jsonl")
CLUSTER_PATH = Path("data/processed/topic_clusters.jsonl")
ENTITY_SUMMARY_PATH = Path("data/processed/entity_summary.json")
ENTITY_DIR = Path("data/processed/entities")
DIGEST_PATH = Path("data/processed/daily_digest.md")

ENTITY_SECTION_TITLES = {
    "Top Emerging Entities",
    "Most-mentioned Entities",
    "Cross-source Entities",
}


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
        or item.get("source_handle")
        or item.get("author_handle")
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


def is_enabled(item, key, default=True):
    value = item.get(key, default)

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() not in {"false", "0", "no", "off"}


def load_clusters(cluster_path=CLUSTER_PATH):
    cluster_path = Path(cluster_path)

    if not cluster_path.exists():
        return []

    clusters = []

    for line in cluster_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        cluster = json.loads(line)

        if int(cluster.get("cluster_size", 0)) < 2:
            continue

        clusters.append(cluster)

    return sorted(
        clusters,
        key=lambda c: int(c.get("cluster_size", 0)),
        reverse=True,
    )


def load_entity_summary(entity_summary_path=ENTITY_SUMMARY_PATH, log_path=LOG_PATH):
    entity_summary_path = Path(entity_summary_path)

    if not entity_summary_path.exists():
        build_entity_summary(
            log_path=log_path,
            output_path=entity_summary_path,
            entity_dir=ENTITY_DIR,
        )

    if not entity_summary_path.exists():
        return {
            "generated_at": "",
            "entity_count": 0,
            "entities": [],
            "top_emerging_entities": [],
            "most_mentioned_entities": [],
            "cross_source_entities": [],
        }

    return json.loads(entity_summary_path.read_text(encoding="utf-8"))


def format_entity_bullet(entity):
    verticals = ", ".join(entity.get("associated_verticals", [])[:5]) or "Unclassified"

    return (
        f"- **{entity.get('entity_name', 'Unknown')}** — "
        f"trend: {entity.get('trend_label', 'stable')} — "
        f"mentions: {entity.get('mention_count', 0)} — "
        f"sources: {entity.get('source_diversity', 0)} — "
        f"avg importance: {entity.get('average_importance_score', 0)} — "
        f"latest: {entity.get('latest_mention_timestamp', '')} — "
        f"verticals: {verticals}"
    )


def build_entity_sections(entity_summary):
    sections = []

    section_map = [
        ("Top Emerging Entities", entity_summary.get("top_emerging_entities", [])),
        ("Most-mentioned Entities", entity_summary.get("most_mentioned_entities", [])),
        ("Cross-source Entities", entity_summary.get("cross_source_entities", [])),
    ]

    for title, entities in section_map:
        if not entities:
            continue

        sections.append((title, entities))

    return sections


def write_digest(
    log_path=LOG_PATH,
    cluster_path=CLUSTER_PATH,
    entity_summary_path=ENTITY_SUMMARY_PATH,
    digest_path=DIGEST_PATH,
):
    log_path = Path(log_path)
    cluster_path = Path(cluster_path)
    entity_summary_path = Path(entity_summary_path)
    digest_path = Path(digest_path)

    digest_path.parent.mkdir(parents=True, exist_ok=True)
    entity_summary = load_entity_summary(entity_summary_path, log_path=log_path)
    clusters = load_clusters(cluster_path)
    groups = defaultdict(list)
    seen = set()

    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue

            item = json.loads(line)

            item_id = get_item_id(item)

            if item_id in seen:
                continue

            if not is_enabled(item, "digest_enabled", True):
                continue

            seen.add(item_id)

            verticals = item.get("verticals") or ["Unclassified"]
            primary_vertical = verticals[0] if verticals else "Unclassified"
            groups[primary_vertical].append(item)

    with digest_path.open("w", encoding="utf-8") as f:
        f.write("# Daily Intelligence Digest\n\n")
        f.write(
            f"Generated: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}\n\n"
        )

        if clusters:
            f.write("## Topic Clusters\n\n")

            for cluster in clusters[:5]:
                keywords = ", ".join(cluster.get("keywords", [])[:6])
                cluster_size = cluster.get("cluster_size", 0)

                f.write(
                    f"- **{cluster_size} related items** — "
                    f"keywords: {keywords}\n"
                )

            f.write("\n")

        if not groups:
            f.write("No new classified items.\n\n")

        for vertical in sorted(groups):
            items = sorted(
                groups[vertical],
                key=get_importance_score,
                reverse=True,
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

        entity_sections = build_entity_sections(entity_summary)

        for title, entities in entity_sections:
            f.write(f"## {title}\n\n")

            for entity in entities[:5]:
                f.write(f"{format_entity_bullet(entity)}\n")

            f.write("\n")

    return {
        "digest_path": digest_path,
        "cluster_count": len(clusters),
        "entity_count": entity_summary.get("entity_count", 0),
        "entity_section_count": len(entity_sections),
    }


def main():
    result = write_digest()
    print(
        f"Wrote digest to {result['digest_path']} "
        f"with {result['cluster_count']} clusters and "
        f"{result['entity_count']} entities."
    )


if __name__ == "__main__":
    main()
