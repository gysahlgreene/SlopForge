# Creatures

M5 (Creatures/Generic rigs) can generate a four-legged creature and rig it for review (package B1). No creature motion
is produced yet. This page documents the creature asset type, its rig, and the creature-motion provider the track will
use. The design and its packages are in the
[AI motion sources plan](https://github.com/gysahlgreene/SlopForge/blob/docs/ai-motion-sources-plan/docs/superpowers/plans/2026-10-27-ai-motion-sources.md)
(epic [#128](https://github.com/gysahlgreene/SlopForge/issues/128)).

## Rigging a creature (B1)

A creature is the `creature` asset type: a model generated like a prop, on the TRELLIS.2 route, at the character face
budget. Its type declares the limbs the rig is checked against: four legs that stand on the ground (`limbs:
{ground_contact: 4}`). Only quadrupeds are supported for now (owner decision D12). Generate, approve a concept and
approve a material as for any model, then rig the published model:

```sh
slopforge --project ~/UnityProjects/MyGame generate creature wolf "Grey wolf" --material "fur=nonmetal: grey and cream fur"
slopforge --project ~/UnityProjects/MyGame approve wolf <n>
slopforge --project ~/UnityProjects/MyGame approve-texture wolf <n>
slopforge --project ~/UnityProjects/MyGame creature rig wolf            # --seeds 1-8; the type's rig_seeds is 4
slopforge --project ~/UnityProjects/MyGame creature approve-rig wolf --confirm
```

`creature rig` runs SkinTokens once per seed (seeds 1 to N) on the published FBX. The rigging provider is configured as
for characters (`tools.skintokens_*`; [Character rigging](CHARACTER-RIGGING.md)). Blender then checks each raw rig
(`slopforge/creature_rig.py`, measured by `blender/creature_rig.py`):

- **One armature and one root bone.**
- **A bone chain of its own for every declared leg.** The feet are the patches of skin within 4 % of the height above
  the floor. The chain is traced from the bone leading a foot's skin up to the bone the body branches at. It needs three
  bones or more, and must stand the way video2rig's `standing_legs` tests it: its last two bones lead skin within 4 % of
  the height above the floor. A leg whose skin follows a torso bone has no chain, as with a leg TRELLIS.2 painted onto
  the body. So does a foot that shares another foot's chain.
- **Twin legs are symmetric.** They have the same bone count, leave the body at the same bone, and mirror within
  `max_rig_asymmetry` of the height across that bone. The type's 0.05 is a proposal awaiting the owner's ruling. In the
  bounded check, the passing wolf seed mirrored within 0.005 and a failing seed 0.28.
- **Every joint is inside the skin,** by generalized winding number above 0.5.
- **The weights** follow a bone at every vertex, with at most four influences, summing to 1.
- **The rig can be named as a quadruped.** The hind legs leave the body at the root (the hips) and the front legs at a
  chest further up one spine. Besides those, only a tail and one neck may leave them.

Each seed's result is kept as `rig_candidate.seed_N` with its verdict, raw GLB, structure report and front and side
views; a rejected seed stays `failed` with its reasons. A seed that crashes is recorded and the others still run. No
passing seed fails the run, with every candidate kept. A rerun refuses while `Rigging/` exists: move it aside first.

The best passing seed is finished. Best means it mirrors most closely; on a tie, the lower seed wins.

- **Names.** Its bones get video2rig's quadruped names (no humanoid names, and no Unity Humanoid mapping):
  - the body: `Hips`, `Spine1..`, `Chest`, `Neck1..`, `Head`, `Tail1..`;
  - each front leg: `Scapula`, `UpperArm`, `Forearm`, `FrontPaw` and `FrontToes`;
  - each hind leg: `Thigh`, `Shin`, `HindPaw` and `HindToes`, with `.L` and `.R`.
  
  A bone past its chain's names becomes an `…End` bone.
- **Bone axes.** Each bone's tail runs along its chain, and each bone's local X lies across the body, which is how
  video2rig bends a joint.
- **Material.** The source material comes back as in the character route.
- **Outputs.** It is exported as `<name>_rig.fbx` and a packed `<name>_rig.blend` under `Creatures/<name>/Rigging/`,
  registered as the pending `rig` artifact. Next to it are `Review/seed_sheet.png`, with every seed's views and verdict,
  and `Review/contact_sheet.png`, with six poses: rest, left foreleg lifted, right hind leg lifted, head up and turned,
  tail up and aside, and spine bent.
- **`fit_bones`.** The manifest records the bones video2rig must fit (`rigging.fit_bones`): every named bone but the
  ends, declared rather than left to the tool's auto rule. That rule drops bones leading under 0.4 % of the skin, such
  as a generated wolf's paws ([#139](https://github.com/gysahlgreene/SlopForge/issues/139)). Each bone's share of the
  skin is in its structure report.

The structure checks are structural evidence only. Deformation is judged by a person: `approve-rig --confirm` records
that review. It refuses a rig changed since it was made, or one whose lineage's output rights are `unknown` or
`restricted`. The facing comes from the highest skin (the head end), so check the sheet's left and right legs: a raised
tail higher than the head would swap them.

**Verified (2026-10-27):** offline tests on a four-legged box fixture and a local Blender test of the fixture through
the check, the names and the finish. The live gate runs a configured project's published creature:

```sh
SLOPFORGE_RUN_SKINTOKENS=1 SLOPFORGE_PROJECT_ROOT=<project> SLOPFORGE_CREATURE=<name> \
  python -m pytest -q -s tests/test_creature_pipeline.py -k external
```

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
