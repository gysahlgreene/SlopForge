#!/bin/bash
# Install the OmniPart environment used by weapons with moving parts (docs/WEAPONS.md, Moving parts).
# Run on the GPU host; then set tools.omnipart_python and tools.omnipart_checkout in the project's ai/project.yaml.
# Usage: install-omnipart.sh [directory]   (default ~/SlopForgeOmniPart; needs curl, an NVIDIA driver for CUDA 12.1
# and about 20 GB). The host needs no CUDA toolkit or sudo: micromamba (BSD-3) supplies CUDA 12.1 nvcc and GCC 11.
# Versions verified on 2026-10-25 (H100): Python 3.10 for the repository's cp310 wheels (flash-attn 2.7.0.post2,
# diff_gaussian_rasterization, nvdiffrast), torch 2.4.0 + cu121, setuptools below 81 (lightning 2.2 imports
# pkg_resources). OmniPart's layout stage (NVIDIA PartField, non-commercial) is not used; only its MIT part synthesis.
set -eu
DIR=${1:-$HOME/SlopForgeOmniPart}
mkdir -p "$DIR"; cd "$DIR"
export MAMBA_ROOT_PREFIX=$DIR/mamba
MICROMAMBA_VERSION=2.9.0   # verified 2026-10-25
[ -x "$DIR/bin/micromamba" ] || curl -Ls "https://micro.mamba.pm/api/micromamba/linux-64/$MICROMAMBA_VERSION" | tar -xj -C "$DIR" bin/micromamba
[ -x "$DIR/omnipart/bin/python" ] || "$DIR/bin/micromamba" create -y -p "$DIR/omnipart" -c conda-forge \
  python=3.10 cuda-version=12.1 cuda-nvcc cuda-cudart-dev cuda-libraries-dev gxx_linux-64=11 git ninja
E=$DIR/omnipart; P=$E/bin/python
export CUDA_HOME=$E PATH=$E/bin:$PATH CC=$E/bin/x86_64-conda-linux-gnu-gcc CXX=$E/bin/x86_64-conda-linux-gnu-g++
export CPLUS_INCLUDE_PATH=$E/include:$E/targets/x86_64-linux/include LIBRARY_PATH=$E/lib:$E/targets/x86_64-linux/lib
export TORCH_CUDA_ARCH_LIST=9.0 MAX_JOBS=16
OMNIPART_REVISION=ceb1a4ff2d279a57a673d0f65954735c6bf8231c   # the revision the live runs used (2026-10-25)
[ -d "$DIR/OmniPart" ] || git clone -q https://github.com/HKU-MMLab/OmniPart "$DIR/OmniPart"
cd "$DIR/OmniPart" && git checkout -q "$OMNIPART_REVISION"
$P -m pip install -q torch==2.4.0 torchvision==0.19.0 --index-url https://download.pytorch.org/whl/cu121
$P -c "import torch; assert torch.cuda.is_available(); print('torch', torch.__version__, torch.version.cuda)"
# detectron2 and segment-anything serve the interactive demo's segmentation; the pipeline supplies its own masks.
grep -v 'detectron2\|segment-anything' requirements.txt > /tmp/omnipart-requirements.txt
$P -m pip install -q pybind11 cython wheel "setuptools<81"
$P -m pip install -q --no-build-isolation -r /tmp/omnipart-requirements.txt
$P -m pip install -q "setuptools<81" pytz psutil scikit-learn yacs einops
$P -c "import spconv, flash_attn, nvdiffrast, diff_gaussian_rasterization, xformers, pkg_resources; print('omnipart environment ready')"
echo "tools.omnipart_python: $P"
echo "tools.omnipart_checkout: $DIR/OmniPart"
