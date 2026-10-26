"""Run one of processing/'s tools in its own environment on a GPU host over SSH.

The part-mask models and OmniPart live in environments of their own, on tools.parts_host like SkinTokens: the inputs
are copied into a fresh work directory there, the script is piped to that environment's Python with a request JSON,
and the outputs are copied back. Nothing is installed on the host by the pipeline.
"""
import json
import re
import shlex
import subprocess
import tempfile
from pathlib import Path, PurePosixPath


def run_remote_tool(host, python, script, request, uploads, downloads, *, label="parts", cwd=None, env=None):
    """Run `script` on `host` with `request` (a JSON-able dict) and bring its outputs back.

    uploads: remote file name inside the work directory -> local path; any request value equal to that name is
    replaced by the remote path, and request["out_dir"] is the remote output directory. downloads: path relative to
    that output directory ("." for all of it) -> local destination. cwd runs the script from a directory (OmniPart
    imports from its checkout); env is exported before it. Raises RuntimeError with the script's last stderr line.
    """
    ssh = ["ssh", "-o", "BatchMode=yes", host]
    made = subprocess.run(ssh + ["mktemp", "-d", f"/tmp/slopforge-{label}-XXXXXX"], capture_output=True, text=True,
                          check=False)
    # Shell start-up files may print first; cleanup runs `rm -rf` on this path, so accept only mktemp's line.
    work = (made.stdout.strip().splitlines() or [""])[-1].strip()
    if made.returncode != 0 or not re.fullmatch(rf"/tmp/slopforge-{label}-[A-Za-z0-9]+", work):
        raise RuntimeError(f"Could not create a {label} work directory on {host}")
    work = PurePosixPath(work)
    try:
        with tempfile.TemporaryDirectory() as temporary:
            request_path = Path(temporary) / "request.json"
            remote = {name: str(work / name) for name in uploads}

            def placed(value):  # an upload's name anywhere in the request, nested dicts and lists included
                if isinstance(value, str):
                    return remote.get(value, value)
                if isinstance(value, dict):
                    return {key: placed(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [placed(item) for item in value]
                return value
            request_path.write_text(json.dumps({**placed(request), "out_dir": str(work / "out")}))
            for local, target in (*((path, work / name) for name, path in uploads.items()),
                                  (request_path, work / "request.json")):
                if subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(local), f"{host}:{target}"],
                                  check=False).returncode != 0:
                    raise RuntimeError(f"Could not upload {Path(local).name} to {host}")
        command = shlex.join([python, "-", str(work / "request.json")])
        if env:
            command = " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items()) + " " + command
        if cwd:
            command = f"cd {shlex.quote(cwd)} && " + command
        completed = subprocess.run(ssh + [command], input=Path(script).read_text(), capture_output=True, text=True,
                                   check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"{Path(script).name} on {host} failed: "
                               + (completed.stderr.strip().splitlines() or ["no output"])[-1])
        for name, destination in downloads.items():
            Path(destination).mkdir(parents=True, exist_ok=True) if name == "." else Path(destination).parent.mkdir(
                parents=True, exist_ok=True)
            source = f"{host}:{work / 'out'}/." if name == "." else f"{host}:{work / 'out' / name}"
            if subprocess.run(["scp", "-q", "-r", "-o", "BatchMode=yes", source, str(destination)],
                              check=False).returncode != 0:
                raise RuntimeError(f"Could not download {name} from {host}")
    finally:
        subprocess.run(ssh + ["rm", "-rf", "--", str(work)], check=False)
