#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${SLOPFORGE_PYTHON:-$ROOT/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then PYTHON="$(command -v python3 || true)"; fi
if [ -z "$PYTHON" ]; then echo "Python 3 is required." >&2; exit 1; fi
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" exec "$PYTHON" -m slopforge.cli doctor "$@"
