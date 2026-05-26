import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path
import urllib.error
import urllib.request


DEFAULT_OUTBOX_DIR = Path("data/outbox/slack/daily-intel-digest")
DATE_FORMAT = "%Y-%m-%d"


def is_valid_date(value):
    if not value:
        return True

    try:
        datetime.strptime(value, DATE_FORMAT)
    except ValueError:
        return False

    return True


def resolve_payload_path(outbox_dir, run_date=""):
    outbox_dir = Path(outbox_dir)

    if run_date:
        payload_path = outbox_dir / f"{run_date}.json"
        return payload_path if payload_path.exists() else None

    payload_paths = sorted(outbox_dir.glob("*.json"))

    if not payload_paths:
        return None

    return payload_paths[-1]


def load_payload(payload_path):
    payload_path = Path(payload_path)
    return json.loads(payload_path.read_text(encoding="utf-8"))


def build_slack_message(payload):
    if isinstance(payload, dict):
        text = payload.get("text")

        if isinstance(text, str) and text.strip():
            return text.strip()

        title = str(payload.get("title") or "AEON digest").strip()
        date = str(payload.get("date") or "").strip()
        top_alerts_count = payload.get("top_alerts_count")
        promoted_to_hermes_count = payload.get("promoted_to_hermes_count")

        parts = [title if not date else f"{title} ({date})"]

        if top_alerts_count is not None:
            parts.append(f"{top_alerts_count} alert(s)")

        if promoted_to_hermes_count is not None:
            parts.append(f"{promoted_to_hermes_count} Hermes promotions")

        return " | ".join(parts)

    return json.dumps(payload, indent=2, sort_keys=True)


def post_to_slack(webhook_url, message, timeout=10):
    body = json.dumps({"text": message}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", None)

        if status is None:
            status = response.getcode()

        if status is not None and int(status) >= 400:
            raise RuntimeError(f"Slack webhook returned HTTP {status}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Send the latest AEON Slack outbox payload to a webhook."
    )
    parser.add_argument(
        "--outbox-dir",
        default=str(DEFAULT_OUTBOX_DIR),
        help="Directory that contains Slack-safe outbox payloads.",
    )
    parser.add_argument(
        "--date",
        default="",
        help="Send a specific payload partition date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--preview",
        "--dry-run",
        action="store_true",
        dest="preview",
        help="Print the Slack message without sending it.",
    )

    args = parser.parse_args(argv)

    if not is_valid_date(args.date):
        logging.warning("Invalid --date value %r; expected YYYY-MM-DD.", args.date)
        return 0

    payload_path = resolve_payload_path(args.outbox_dir, args.date)

    if payload_path is None:
        logging.warning(
            "No Slack outbox payload found in %s.",
            Path(args.outbox_dir),
        )
        return 0

    try:
        payload = load_payload(payload_path)
        message = build_slack_message(payload)
    except Exception as exc:  # noqa: BLE001
        logging.warning("Unable to read Slack outbox payload %s: %s", payload_path, exc)
        return 0

    if args.preview:
        print(message)
        return 0

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

    if not webhook_url:
        print("No SLACK_WEBHOOK_URL configured; skipping Slack delivery.")
        return 0

    try:
        post_to_slack(webhook_url, message)
    except (urllib.error.URLError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        logging.warning("Slack posting failed for %s: %s", payload_path, exc)
        return 0

    print(f"Sent Slack outbox payload from {payload_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
