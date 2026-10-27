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
exchanges files with it. It never bundles or patches it, and no SlopForge module imports it, so SlopForge's code stays
MIT. The only imports of video2rig happen inside the tool's own Python: the install script's self-check and the
preflight's probe. `tests/test_video2rig_provider.py` fails if any module under `slopforge/`, `processing/`,
`blender/` or `scripts/` imports it, and the preflight refuses a modified checkout. If you offer SlopForge as a service that runs video2rig for other people, you must offer them the source
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
asset_pipeline:
  providers:
    video2rig:
      type: local_tool
      python: ~/SlopForgeVideo2rig/.venv/bin/python                # the SlopForge machine
      checkout: ~/SlopForgeVideo2rig/video2rig
      train_host: <ssh host>                                       # leave the train_* keys unset when this
      train_python: /home/<user>/SlopForgeVideo2rig/.venv/bin/python   # machine has the CUDA card
      train_checkout: /home/<user>/SlopForgeVideo2rig/video2rig
```

The `tools.video2rig_*` keys it was first configured with still work; the providers map wins when both are set.

The tool loads its backbone without naming a revision. SlopForge always runs it with `HF_HOME=<dir>/hf`,
`HF_HUB_CACHE=<dir>/hf/hub` and `HF_HUB_OFFLINE=1`, so that load reads the pinned snapshot and never the network. It
also drops any `HUGGINGFACE_HUB_CACHE`, `TRANSFORMERS_CACHE` or `PYTHONPATH` from the caller's environment. A
user's own cache setting would otherwise outrank `HF_HOME`, and `PYTHONPATH` could put another torch or
transformers ahead of the venv's.

**What runs where.** These follow the owner's decision D15 (a) and keep Blender on the SlopForge machine:

- On the SlopForge machine: the rig export, the start picture and the training renders
  (`reader.prepare --skip-train`). Reading and fitting clips (`check`, `run --cpu`, `review`) and the Blender import
  of the motion also run there.
- On the GPU provider: `reader.train`, in bfloat16.

Sending a project to the GPU provider for `reader.train` and bringing the reader back is not built yet; it belongs
to package B3. Until then the client runs `train` only on a machine with no `train_host` set, and
refuses it otherwise.

The client builds each documented command line and runs it with the provider's Python in its checkout. It makes
every path absolute first, because a relative one would land inside the pinned checkout. `train` requires a step
count, because the tool's default of 8 minutes trains for however many steps the card manages. Before each step,
the client deletes the step's previous output, so a step that crashes cannot hand back an earlier take's answer. It reads back
`reader-train.json`, `check.json` (a FAIL verdict is the check's answer, not an error) and `report.json`. It never
builds video2rig's older road, the BootsTAPIR point tracker. It refuses `run` when the creature has no
`reader/reader.pt`, because the tool would otherwise fall back to that road without saying so.

**Preflight.** `slopforge doctor` lists the provider once `providers.video2rig` (or a `tools.video2rig_*` key) is set. It shows one line for this
machine and one for the training machine, each with the output-rights status. Each preflight passes only when all of
these hold:

- The checkout is at the pinned commit, with no modified or untracked files.
- The tool's modules, torch and transformers import in its venv.
- The DINOv2 snapshot is the pinned revision, with the pinned `model.safetensors` sha256, and loads offline.
- On the SlopForge machine, ffmpeg (or `V2R_FFMPEG`) and Blender are found.
- On the training machine, a CUDA card with bfloat16 is present.

The training machine's preflight runs over SSH, by streaming the standard-library `video2rig_runtime.py` to the
tool's own Python. A missing setting or an unreadable reply rejects that machine only. A reply of `ready` for other
pins counts as unverified.

`identity()` builds the record a creature stage will copy into provenance once one exists (package B3):
`{name: video2rig, model_id: facebook/dinov2-small, revision, weights_sha256}`. `revision` is the commit and
`weights_sha256` is the creature's `reader.pt`, or `unavailable` before one is trained. The record also carries the
DINOv2 revision and sha256, the torch and transformers versions with the device, and the output rights.

**Verified so far (2026-10-27, step 0 of package V0):**

- Linux, NVIDIA H100: the install script ran unmodified, and its import self-check passed with CUDA bfloat16.
- The same machine trained a reader for one step, on renders of a box-built quadruped fixture. This took 7 s and wrote
  `reader.pt` and `reader-train.json`. One step proves only that the tool runs; it does not show accuracy.
- macOS (Apple silicon): the install ran with CPU wheels. Run by hand with the tool's own scripts, the fixture's rig
  export, start picture and `reader.prepare --skip-train` (40 poses) all worked.

Step 0 ran by hand with the tool's own commands, not through SlopForge's client. On 2026-10-27, after the review
fixes, the install script ran again on both machines, and on macOS with a stray `HF_HUB_CACHE` and `PYTHONPATH` set.
The preflight passes on both: the H100 (CUDA bfloat16, over SSH) and macOS (CPU).

**Not verified yet:**

- The client's step runner against the real tool. It has run only against a stand-in in the offline tests.
- Reading and fitting a clip on any machine.
- Any real creature.
- The accuracy exam on synthetic motion (package B3).
- Windows. The install script is shell-only, so Windows needs WSL.

To check an install, run this with a project whose `ai/project.yaml` sets the keys above:

```sh
SLOPFORGE_RUN_VIDEO2RIG=1 SLOPFORGE_PROJECT_ROOT=<project> python -m pytest -q -s tests/test_video2rig_provider.py -k external
```

## The motion exam, v1

The exam measures how well video2rig reads back a motion SlopForge already knows. The owner set these limits on
2026-10-27 (decisions D5 and D7 of the plan), from the four clips of the bounded check
[#129](https://github.com/gysahlgreene/SlopForge/issues/129): two creatures, two motions each
([evidence](media/creature-motion-spike-2026-10/README.md)).

**Scope.** Exam v1 judges synthetic motion only: a known motion rendered through video2rig's own two cameras and
studio, with no video model. That is the best case, so a creature that fails here will not do better on generated
video. The limits can be revised with new evidence, and passing them qualifies nothing on its own.

**Limits per exam clip, with the spike's measurements:**

| Metric | Limit | Fox random | Fox walk | Wolf random | Wolf gait |
| --- | --- | --- | --- | --- | --- |
| Bone direction error, median over all fitted bones | ≤ 5° | 2.7° | 3.1° | 2.7° | 2.0° |
| Worst non-tail bone's median | ≤ 10° | 5.6° | 5.5° | 5.5° | 3.5° |
| Worst non-tail bone's p95 | ≤ 25° | 16.2° | **155.7°** ¹ | 10.8° | 10.2° |
| Worst tail bone's p95 | ≤ 40° | 27.2° | 18.6° | 24.9° | 28.5° |
| Joint error with travel removed, median (share of height) | ≤ 0.025 | 0.011 | 0.020 | 0.008 | 0.007 |
| Joint error with travel removed, p95 | ≤ 0.10 | 0.050 | 0.071 | 0.029 | 0.064 |
| Detection, side view | ≥ 0.85 | 0.98 | 0.995 | 0.92 | 0.92 |
| Detection, front view | ≥ 0.45 | 0.69 | 0.65 | 0.56 | 0.59 |
| Limb-end tips read in their better view (share of frames) | ≥ 0.95 | 1.0 | 1.0 | 1.0 | 1.0 |
| Near/far swap rate, worst left/right pair | ≤ 0.15 | 0.00 | 0.14 | 0.01 | 0.096 |
| D7: views disagree, body (share of height) | ≤ 1.5 % | 0.93 % | 0.57 % | 0.25 % | 0.26 % |
| D7: views disagree, limbs | ≤ 2.0 % | 0.76 % | 1.05 % | 0.27 % | 0.27 % |

¹ Fails. Three bones are over the limit: both front paws (155.7° and 141.4°) and the right forearm (48.3°).

**What fails.** Only the Fox walk fails, on those three bones. It also fails with the paws' range declared at fit time
(127°) and with it declared before the reader trained (156°, swap rate 0.16). In every frame the front view misreads,
the lifted front paw is drawn over the hind leg behind it, so the reader guesses. The fit then weighs that guess
against the side view's correct reading ([#140](https://github.com/gysahlgreene/SlopForge/issues/140)). The fit's
weighting goes upstream to video2rig. A three-quarter front camera (`render_start.py --views three-quarter,side`) is
untested.
The closest passes are the wolf gait's swap rate (0.096), the Fox walk's joint median (0.020) and the wolf random
clip's front detection (0.56).

**How each metric is measured:**

- *Bone direction error:* the angle between the fitted and the true head-to-tail direction, per bone per frame. Tail
  bones have their own limit because the fit drives them with springs.
- *Joint error with travel removed:* the 3-D miss per joint per frame, after taking the root's translation out of both
  the fit and the truth, over the creature's height. World-space error belongs to D9
  ([#141](https://github.com/gysahlgreene/SlopForge/issues/141)), because clips walked on the spot come back with travel.
- *Detection:* the share of frames in which the reader reads a joint at confidence ≥ 0.4, the fit's own "unsure"
  limit. The front view never sees the hips, spine and tail base, so its limit is lower.
- *Swap rate:* per left/right pair, the share of frames in which the fit puts the far limb near. Only frames where the
  true pair is more than 2 % of the height apart in the body's side plane count.
- *Views disagree (D7):* the body and limb figures from video2rig's `check`. The tool fails a clip whose body is over
  1.5 % and only warns on limbs over 2 %. SlopForge fails both. A generated clip that fails is regenerated, not repaired.

**When a result counts.** An exam result counts only when all three of these hold:

- every frame was compared;
- the truth matches the render's own joint labels;
- the truth stays inside the joint ranges declared for the reader.

D7's frame-rate tolerance is not set yet.
