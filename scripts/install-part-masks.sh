#!/bin/sh
# Install the part-mask environment (Florence-2 + SAM 2.1) used by `--part` (docs/WEAPONS.md).
# Run on the GPU host; then set tools.parts_host and tools.parts_python in the project's ai/project.yaml.
# Usage: install-part-masks.sh [directory]   (default ~/SlopForgeParts; needs uv and an NVIDIA driver for CUDA 12.8)
set -eu
DIR=${1:-$HOME/SlopForgeParts}
mkdir -p "$DIR"
uv venv "$DIR/.venv" --python 3.12
# Versions verified on 2026-10-24 (H100): transformers 5.20.1 ships Florence-2 and SAM 2 natively.
uv pip install --python "$DIR/.venv/bin/python" torch==2.7.0 torchvision==0.22.0 \
  --index-url https://download.pytorch.org/whl/cu128
uv pip install --python "$DIR/.venv/bin/python" "transformers==5.20.1" pillow numpy huggingface_hub
"$DIR/.venv/bin/python" -c "import transformers; assert hasattr(transformers, 'Florence2ForConditionalGeneration') and hasattr(transformers, 'Sam2Model'); print('part-mask environment ready')"
echo "tools.parts_python: $DIR/.venv/bin/python"
