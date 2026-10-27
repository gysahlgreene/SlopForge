# Creatures

M5 (Creatures/Generic rigs) has groundwork only: no creature asset, rig or motion is produced by SlopForge yet. This
page documents the creature-motion provider the track will use. The design and its packages are in the
[AI motion sources plan](https://github.com/gysahlgreene/SlopForge/blob/docs/ai-motion-sources-plan/docs/superpowers/plans/2026-10-27-ai-motion-sources.md)
(epic [#128](https://github.com/gysahlgreene/SlopForge/issues/128)).

## video2rig

[video2rig](https://github.com/canitcode/video2rig) reads a creature's motion from a generated two-view video (front
and side in one frame). It trains a joint reader on renders of the creature's own rig with DINOv2-small, then fits the
rig to the reading, frame by frame. SlopForge runs it as a `local_tool` provider (`slopforge/backends/video2rig.py`).

**Licence.** video2rig is AGPL-3.0. SlopForge runs it as a separate program from its own checkout and environment, and
exchanges files with it. It never imports, bundles or patches it, so SlopForge's code stays MIT.
`tests/test_video2rig_provider.py` fails if any module under `slopforge/`, `processing/`, `blender/` or `scripts/`
imports it. If you offer SlopForge as a service that runs video2rig for other people, you must offer them the source
of the video2rig you run (`THIRD_PARTY_NOTICES.md`). Its outputs are recorded as `cleared` (read 2026-10-27). A clip's
rights still depend on the video it was read from.

**Install** on the SlopForge machine and on the NVIDIA machine that trains readers. On one NVIDIA workstation, install
it once. You need git, `uv` and ffmpeg (ffmpeg on the SlopForge machine only):

```sh
scripts/install-video2rig.sh            # default ~/SlopForgeVideo2rig; about 6 GB
```

The script checks out the pinned commit (`55d51b3`), its only one, and makes a Python 3.12 venv. It uses torch 2.7.0
(CUDA 12.8 wheels on Linux, CPU wheels on macOS) and transformers 5.20.1. It downloads `facebook/dinov2-small` at
revision `ed25f3a3` into `<dir>/hf`, imports the tool, and prints the settings for `ai/project.yaml`:

```yaml
tools:
  video2rig_python: ~/SlopForgeVideo2rig/.venv/bin/python     # the SlopForge machine
  video2rig_checkout: ~/SlopForgeVideo2rig/video2rig
  video2rig_train_host: <ssh host>                              # leave the train_* keys unset when this machine
  video2rig_train_python: /home/<user>/SlopForgeVideo2rig/.venv/bin/python   # has the CUDA card
  video2rig_train_checkout: /home/<user>/SlopForgeVideo2rig/video2rig
```

The tool loads its backbone without naming a revision. SlopForge always runs it with `HF_HOME=<dir>/hf` and
`HF_HUB_OFFLINE=1`, so that load reads the pinned snapshot and never the network.

**What runs where.** These follow the owner's decision D15 (a) and keep Blender on the SlopForge machine:

- On the SlopForge machine: the rig export, the start picture and the training renders
  (`reader.prepare --skip-train`). Reading and fitting clips (`check`, `run --cpu`, `review`) and the Blender import
  of the motion also run there.
- On the GPU provider: `reader.train`, in bfloat16.

The client builds each documented command line and runs it with the provider's Python in its checkout. It reads back
`reader-train.json`, `check.json` (a FAIL verdict is the check's answer, not an error) and `report.json`. It never
builds video2rig's older road, the BootsTAPIR point tracker. It refuses `run` when the creature has no
`reader/reader.pt`, because the tool would otherwise fall back to that road without saying so.

**Preflight.** `slopforge doctor` lists the provider once any `video2rig_*` key is set. It shows one line for this
machine and one for the training machine, each with the output-rights status. Each preflight passes only when all of
these hold:

- The checkout is at the pinned commit, with no modified or untracked files.
- The tool's modules, torch and transformers import in its venv.
- The DINOv2 snapshot is the pinned revision, with the pinned `model.safetensors` sha256, and loads offline.
- On the SlopForge machine, ffmpeg (or `V2R_FFMPEG`) and Blender are found.
- On the training machine, a CUDA card with bfloat16 is present.

The training machine's preflight runs over SSH, by streaming the standard-library `video2rig_runtime.py` to the
tool's own Python. The identity a stage records is
`{name: video2rig, model_id: facebook/dinov2-small, revision, weights_sha256}`. `revision` is the commit and
`weights_sha256` is the creature's `reader.pt`, or `unavailable` before one is trained. The record also carries the
DINOv2 revision and sha256 and the output rights.

**Verified so far (2026-10-27, step 0 of package V0):**

- Linux, NVIDIA H100: the install script ran unmodified, and its import self-check passed with CUDA bfloat16.
- The same machine trained a reader for one step, on renders of a box-built quadruped fixture. This took 7 s and wrote
  `reader.pt` and `reader-train.json`. One step proves only that the tool runs; it does not show accuracy.
- macOS (Apple silicon): the install ran with CPU wheels. Run by hand with the tool's own scripts, the fixture's rig
  export, start picture and `reader.prepare --skip-train` (40 poses) all worked.

**Not verified yet:**

- Reading and fitting a clip on any machine.
- Any real creature.
- The accuracy exam on synthetic motion (package B3).
- Windows. The install script is shell-only, so Windows needs WSL.

To check an install, run this with a project whose `ai/project.yaml` sets the keys above:

```sh
SLOPFORGE_RUN_VIDEO2RIG=1 SLOPFORGE_PROJECT_ROOT=<project> python -m pytest -q -s tests/test_video2rig_provider.py -k external
```
