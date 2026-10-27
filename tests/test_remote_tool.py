import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slopforge.failures import StageFailure
from slopforge.remote_tool import run_remote_tool


class RemoteToolTests(unittest.TestCase):
    def test_uploads_are_rewritten_to_the_work_dir_and_the_script_runs_from_cwd_with_env(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "concept.png").write_bytes(b"png")
            (root / "tool.py").write_text("print('hi')\n")
            calls, requests = [], []

            def run(command, **kwargs):
                calls.append(command)
                if command[-3:-1] == ["mktemp", "-d"]:
                    return subprocess.CompletedProcess(command, 0, "Welcome\n/tmp/slopforge-omnipart-abc123\n", "")
                if command[0] == "scp" and str(command[-2]).endswith("request.json"):
                    requests.append(json.loads(Path(command[-2]).read_text()))
                if command[0] == "scp" and command[-1] == str(root / "out"):
                    (root / "out").mkdir(exist_ok=True)
                    (root / "out/parts.json").write_text("{}")
                return subprocess.CompletedProcess(command, 0, "", "")
            with patch("slopforge.remote_tool.subprocess.run", side_effect=run):
                run_remote_tool("gpu", "/opt/env/bin/python", root / "tool.py",
                                {"image": "concept.png", "seed": 3, "masks": {"grip": "grip.png"},
                                 "extra": ["grip.png", 7]},
                                {"concept.png": root / "concept.png", "grip.png": root / "concept.png"},
                                {".": root / "out"}, label="omnipart", cwd="/opt/omnipart",
                                env={"SPCONV_ALGO": "native"})
            self.assertEqual(calls[0], ["ssh", "-o", "BatchMode=yes", "gpu", "mktemp", "-d", "/tmp/slopforge-omnipart-XXXXXX"])
            self.assertEqual(requests, [{"image": "/tmp/slopforge-omnipart-abc123/concept.png", "seed": 3,
                                         "masks": {"grip": "/tmp/slopforge-omnipart-abc123/grip.png"},
                                         "extra": ["/tmp/slopforge-omnipart-abc123/grip.png", 7],
                                         "out_dir": "/tmp/slopforge-omnipart-abc123/out"}])  # nested names too
            script = next(command for command in calls if command[0] == "ssh" and "python" in command[-1])
            self.assertEqual(script[-1], "cd /opt/omnipart && SPCONV_ALGO=native /opt/env/bin/python - "
                                         "/tmp/slopforge-omnipart-abc123/request.json")
            self.assertTrue((root / "out/parts.json").is_file())
            self.assertEqual(calls[-1], ["ssh", "-o", "BatchMode=yes", "gpu", "rm", "-rf", "--",
                                         "/tmp/slopforge-omnipart-abc123"])

    def test_a_failing_script_raises_with_its_last_stderr_line_and_still_cleans_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tool.py").write_text("")
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                if command[-3:-1] == ["mktemp", "-d"]:
                    return subprocess.CompletedProcess(command, 0, "/tmp/slopforge-omnipart-abc123\n", "")
                if command[0] == "ssh" and "python" in command[-1]:
                    return subprocess.CompletedProcess(command, 1, "", "Traceback\nRuntimeError: no GPU\n")
                return subprocess.CompletedProcess(command, 0, "", "")
            with patch("slopforge.remote_tool.subprocess.run", side_effect=run), \
                    self.assertRaisesRegex(RuntimeError, "no GPU") as raised:
                run_remote_tool("gpu", "python", root / "tool.py", {}, {}, {".": root / "out"}, label="omnipart")
            self.assertEqual(calls[-1][-3:], ["-rf", "--", "/tmp/slopforge-omnipart-abc123"])
            # A typed failure, still a RuntimeError for callers that catch that.
            self.assertIsInstance(raised.exception, StageFailure)
            self.assertEqual(raised.exception.category, "environment")

    def test_a_hung_run_times_out_as_an_environment_failure_and_still_cleans_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tool.py").write_text("")
            calls, timeouts = [], []

            def run(command, **kwargs):
                calls.append(command)
                timeouts.append(kwargs.get("timeout"))
                if command[-3:-1] == ["mktemp", "-d"]:
                    return subprocess.CompletedProcess(command, 0, "/tmp/slopforge-train-abc123\n", "")
                if command[0] == "ssh" and "python" in command[-1]:
                    raise subprocess.TimeoutExpired(command, kwargs["timeout"])
                return subprocess.CompletedProcess(command, 0, "", "")
            with patch("slopforge.remote_tool.subprocess.run", side_effect=run), \
                    self.assertRaisesRegex(StageFailure, "timed out after 60 s") as raised:
                run_remote_tool("gpu", "python", root / "tool.py", {}, {}, {".": root / "out"}, label="train",
                                timeout=60)
            self.assertEqual(raised.exception.category, "environment")
            self.assertEqual(calls[-1][-3:], ["-rf", "--", "/tmp/slopforge-train-abc123"])
            self.assertEqual(set(timeouts[:-1]), {60})  # every step is bounded, cleanup included
            self.assertIsNotNone(timeouts[-1])

    def test_the_default_timeout_bounds_a_run_at_three_hours(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tool.py").write_text("")
            timeouts = []

            def run(command, **kwargs):
                timeouts.append(kwargs.get("timeout"))
                if command[-3:-1] == ["mktemp", "-d"]:
                    return subprocess.CompletedProcess(command, 0, "/tmp/slopforge-parts-abc123\n", "")
                return subprocess.CompletedProcess(command, 0, "", "")
            with patch("slopforge.remote_tool.subprocess.run", side_effect=run):
                run_remote_tool("gpu", "python", root / "tool.py", {}, {}, {})
            self.assertEqual(timeouts[0], 3 * 3600)

    def test_no_work_directory_is_an_environment_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tool.py").write_text("")
            with patch("slopforge.remote_tool.subprocess.run",
                       return_value=subprocess.CompletedProcess([], 255, "", "Connection refused")), \
                    self.assertRaisesRegex(StageFailure, "work directory") as raised:
                run_remote_tool("gpu", "python", root / "tool.py", {}, {}, {})
            self.assertEqual(raised.exception.category, "environment")


if __name__ == "__main__":
    unittest.main()
