import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "pipeline" / "run_local_pipeline.py"


def load_run_local_pipeline_module():
    spec = importlib.util.spec_from_file_location(
        "run_local_pipeline",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


run_local_pipeline = load_run_local_pipeline_module()


class RunLocalPipelineTests(unittest.TestCase):
    def test_build_subprocess_env_prepends_repo_root_to_pythonpath(self):
        with mock.patch.dict(os.environ, {"PYTHONPATH": "/opt/custom"}, clear=False):
            env = run_local_pipeline.build_subprocess_env()

        self.assertEqual(
            env["PYTHONPATH"],
            os.pathsep.join([str(REPO_ROOT), "/opt/custom"]),
        )

    def test_run_pipeline_passes_repo_root_pythonpath_to_subprocesses(self):
        calls = []

        class DummyResult:
            returncode = 0

        def fake_run(command, cwd=None, env=None):
            calls.append({"command": command, "cwd": cwd, "env": env})
            return DummyResult()

        with mock.patch.dict(os.environ, {"PYTHONPATH": "/opt/custom"}, clear=False):
            with mock.patch.object(run_local_pipeline.subprocess, "run", side_effect=fake_run):
                run_local_pipeline.run_pipeline(
                    [
                        {
                            "label": "Test step",
                            "command": ["/usr/bin/python3", "-c", "print('ok')"],
                        }
                    ]
                )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["cwd"], REPO_ROOT)
        self.assertEqual(
            calls[0]["env"]["PYTHONPATH"],
            os.pathsep.join([str(REPO_ROOT), "/opt/custom"]),
        )

    def test_build_pipeline_steps_prefers_configured_inputs_in_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)

            token_path = temp_dir / "credentials" / "token.json"
            creds_path = temp_dir / "credentials" / "gmail_credentials.json"
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text("token", encoding="utf-8")
            creds_path.write_text("creds", encoding="utf-8")

            pdf_dir = temp_dir / "data" / "intake" / "pdf"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            (pdf_dir / "report.pdf").write_bytes(b"%PDF-1.4\n")

            sources_path = temp_dir / "config" / "sources.yml"
            sources_path.parent.mkdir(parents=True, exist_ok=True)
            sources_path.write_text(
                "\n".join(
                    [
                        "twitter:",
                        "  - handle: aaronjmars",
                        "    name: Aaron J. Mars",
                        "    feed_url: https://example.invalid/feed.xml",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            steps, notes = run_local_pipeline.build_pipeline_steps(
                sources_file=sources_path,
                pdf_input_dir=pdf_dir,
                gmail_token_path=token_path,
                gmail_credentials_path=creds_path,
            )

            self.assertEqual(notes, [])

            labels = [step["label"] for step in steps]
            self.assertEqual(
                labels,
                [
                    "Fetch Gmail intake",
                    "Promote Gmail source candidates",
                    "Ingest local PDFs",
                    "Fetch configured Twitter feeds",
                    "Classify normalized intake",
                    "Summarize / preview items",
                    "Cluster items",
                    "Extract alert candidates",
                    "Promote high-signal items to Hermes",
                    "Build source metrics",
                    "Build entity summary",
                    "Build narrative summary",
                    "Build Hermes synthesis",
                    "Build digest",
                    "Build Slack-safe digest payload",
                    "Build Slack command-center payload",
                ],
            )

    def test_build_pipeline_steps_skips_missing_optional_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            pdf_dir = temp_dir / "data" / "intake" / "pdf"
            sources_path = temp_dir / "config" / "sources.yml"

            steps, notes = run_local_pipeline.build_pipeline_steps(
                sources_file=sources_path,
                pdf_input_dir=pdf_dir,
                gmail_token_path=temp_dir / "credentials" / "token.json",
                gmail_credentials_path=temp_dir / "credentials" / "gmail_credentials.json",
            )

            labels = [step["label"] for step in steps]
            self.assertEqual(
                labels,
                [
                    "Classify normalized intake",
                    "Summarize / preview items",
                    "Cluster items",
                    "Extract alert candidates",
                    "Promote high-signal items to Hermes",
                    "Build source metrics",
                    "Build entity summary",
                    "Build narrative summary",
                    "Build Hermes synthesis",
                    "Build digest",
                    "Build Slack-safe digest payload",
                    "Build Slack command-center payload",
                ],
            )
            self.assertEqual(
                notes,
                [
                    "Skipping Gmail intake: no Gmail token or credentials were found.",
                    f"Skipping PDF ingestion: no PDFs found in {pdf_dir}.",
                    "Skipping Twitter feed ingestion: no feed URLs are configured.",
                ],
            )


if __name__ == "__main__":
    unittest.main()
