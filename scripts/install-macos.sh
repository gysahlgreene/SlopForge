#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  echo "Usage: $0"
  echo "Create a local virtual environment and install SlopForge editable."
  exit 0
fi
if [ "$#" -ne 0 ]; then echo "Usage: $0" >&2; exit 2; fi
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
# pyproject.toml installs rembg[cpu], including the CPU ONNX Runtime backend.
"$ROOT/.venv/bin/python" -m pip install -e "$ROOT"
echo "SlopForge environment ready: $ROOT/.venv"
echo "Activate it with: source \"$ROOT/.venv/bin/activate\""
