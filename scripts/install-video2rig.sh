#!/bin/sh
# Install video2rig (github.com/canitcode/video2rig, AGPL-3.0) as a separately installed tool SlopForge calls through
# its command line only (docs/CREATURES.md, video2rig). Never vendored, imported or modified: a fix goes upstream.
# Run it on the SlopForge machine (Blender renders, reading and fitting on the CPU) and on the configured NVIDIA
# machine that trains readers, local or remote; on one NVIDIA workstation once is enough.
# Usage: install-video2rig.sh [directory]   (default ~/SlopForgeVideo2rig; needs git, uv and ffmpeg; Linux uses CUDA
# 12.8 wheels, macOS the CPU wheels; about 6 GB)
set -eu
DIR=${1:-$HOME/SlopForgeVideo2rig}
VIDEO2RIG_REVISION=55d51b3b9685125a8ea27841d6af9523f6352aa1   # its first and only commit, 2026-10-23
DINOV2_REVISION=ed25f3a31f01632728cabb09d1542f84ab7b0056      # facebook/dinov2-small (Apache-2.0), read unpinned by the tool
mkdir -p "$DIR"
[ -d "$DIR/video2rig" ] || git clone -q https://github.com/canitcode/video2rig "$DIR/video2rig"
git -C "$DIR/video2rig" checkout -q "$VIDEO2RIG_REVISION"
uv venv "$DIR/.venv" --python 3.12 --allow-existing
P=$DIR/.venv/bin/python
# Versions verified on 2026-10-27 (H100, Linux; Apple silicon, macOS): torch and transformers as the part-mask
# environment; transformers 5 because a reader saved with 5 does not load in 4 (video2rig's requirements.txt).
if [ "$(uname)" = Linux ]; then
  uv pip install -q --python "$P" torch==2.7.0 --index-url https://download.pytorch.org/whl/cu128
else
  uv pip install -q --python "$P" torch==2.7.0
fi
uv pip install -q --python "$P" "transformers==5.20.1" huggingface_hub numpy scipy opencv-python threadpoolctl \
  networkx scikit-image
# The backbone at a pinned revision in this install's own cache; SlopForge runs the tool with HF_HUB_OFFLINE=1 against
# it, so the tool's unpinned load resolves to this snapshot (refs/main points at it). HF_HUB_CACHE and the older cache
# variables outrank HF_HOME, and PYTHONPATH could shadow the venv: none of the caller's reach the tool.
v2r_env() { env -u HUGGINGFACE_HUB_CACHE -u TRANSFORMERS_CACHE -u PYTHONPATH HF_HOME="$DIR/hf" \
  HF_HUB_CACHE="$DIR/hf/hub" "$@"; }
v2r_env "$P" - "$DINOV2_REVISION" <<'EOF'
import os, sys
from pathlib import Path
from huggingface_hub import snapshot_download
revision = sys.argv[1]
snapshot_download("facebook/dinov2-small", revision=revision,
                  allow_patterns=["config.json", "model.safetensors", "preprocessor_config.json"])
ref = Path(os.environ["HF_HUB_CACHE"]) / "models--facebook--dinov2-small/refs/main"
ref.parent.mkdir(parents=True, exist_ok=True)
ref.write_text(revision)
EOF
cd "$DIR/video2rig"
v2r_env HF_HUB_OFFLINE=1 "$P" -c "
import torch
import video2rig.check, video2rig.creature, video2rig.reader.net, video2rig.reader.train
from transformers import Dinov2Model
Dinov2Model.from_pretrained('facebook/dinov2-small')
cuda = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
print('video2rig environment ready:', torch.__version__, 'cuda' if cuda else 'cpu')
if not cuda:
    print('note: no CUDA card with bfloat16, so this machine cannot train readers; reading and fitting run here')"
command -v ffmpeg >/dev/null || echo "warning: ffmpeg is not on PATH (the review film needs it; or set V2R_FFMPEG)"
echo "On the SlopForge machine:  tools.video2rig_python: $P"
echo "                           tools.video2rig_checkout: $DIR/video2rig"
echo "On a remote NVIDIA machine: tools.video2rig_train_host: <ssh host>"
echo "                           tools.video2rig_train_python: $P"
echo "                           tools.video2rig_train_checkout: $DIR/video2rig"
