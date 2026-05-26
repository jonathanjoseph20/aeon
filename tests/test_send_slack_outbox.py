import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "ingestion" / "send_slack_outbox.py"


def load_send_slack_outbox_module():
    spec = importlib.util.spec_from_file_location("send_slack_outbox", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


send_slack_outbox = load_send_slack_outbox_module()


class SendSlackOutboxTests(unittest.TestCase):
    def write_payload(self, outbox_dir, date_value, message):
        payload_path = Path(outbox_dir) / f"{date_value}.json"
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_text(
            json.dumps(
                {
                    "date": date_value,
                    "text": message,
                    "title": "Daily Intelligence Digest",
                    "top_alerts_count": 2,
                    "promoted_to_hermes_count": 3,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return payload_path

    def test_preview_prints_specific_payload_without_network(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            outbox_dir = temp_dir / "data" / "outbox" / "slack" / "daily-intel-digest"
            self.write_payload(outbox_dir, "2026-05-24", "Older digest")
            self.write_payload(outbox_dir, "2026-05-25", "Latest digest")

            stdout = io.StringIO()
            with patch.dict(send_slack_outbox.os.environ, {}, clear=True):
                with contextlib.redirect_stdout(stdout):
                    exit_code = send_slack_outbox.main(
                        [
                            "--outbox-dir",
                            str(outbox_dir),
                            "--date",
                            "2026-05-24",
                            "--preview",
                        ]
                    )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stdout.getvalue().strip(), "Older digest")

    def test_send_posts_latest_payload_when_webhook_is_configured(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            outbox_dir = temp_dir / "data" / "outbox" / "slack" / "daily-intel-digest"
            self.write_payload(outbox_dir, "2026-05-24", "Older digest")
            latest_path = self.write_payload(outbox_dir, "2026-05-25", "Latest digest")

            fake_response = unittest.mock.MagicMock()
            fake_response.__enter__.return_value = fake_response
            fake_response.getcode.return_value = 200
            fake_response.status = 200
            fake_response.read.return_value = b"ok"

            with patch.dict(
                send_slack_outbox.os.environ,
                {"SLACK_WEBHOOK_URL": "https://example.invalid/slack"},
                clear=True,
            ):
                with patch.object(
                    send_slack_outbox.urllib.request,
                    "urlopen",
                    return_value=fake_response,
                ) as mock_urlopen:
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout):
                        exit_code = send_slack_outbox.main(
                            [
                                "--outbox-dir",
                                str(outbox_dir),
                            ]
                        )

            self.assertEqual(exit_code, 0)
            self.assertIn(f"Sent Slack outbox payload from {latest_path}", stdout.getvalue())
            self.assertEqual(mock_urlopen.call_count, 1)

            request = mock_urlopen.call_args.args[0]
            body = json.loads(request.data.decode("utf-8"))
            self.assertEqual(body, {"text": "Latest digest"})

    def test_send_logs_warning_when_webhook_post_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            outbox_dir = temp_dir / "data" / "outbox" / "slack" / "daily-intel-digest"
            payload_path = self.write_payload(outbox_dir, "2026-05-25", "Latest digest")

            with patch.dict(
                send_slack_outbox.os.environ,
                {"SLACK_WEBHOOK_URL": "https://example.invalid/slack"},
                clear=True,
            ):
                with patch.object(
                    send_slack_outbox.urllib.request,
                    "urlopen",
                    side_effect=OSError("network down"),
                ) as mock_urlopen:
                    stdout = io.StringIO()
                    with self.assertLogs(level="WARNING") as captured:
                        with contextlib.redirect_stdout(stdout):
                            exit_code = send_slack_outbox.main(
                                [
                                    "--outbox-dir",
                                    str(outbox_dir),
                                ]
                            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(mock_urlopen.call_count, 1)
            self.assertIn("Slack posting failed", "\n".join(captured.output))
            self.assertIn(str(payload_path), "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
