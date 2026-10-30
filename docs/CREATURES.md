# Creatures

M5 (Creatures/Generic rigs) can generate a four-legged creature, rig it for review (package B1), and calibrate its
video2rig views and render known motions (B2), train its joint reader and examine it on a known motion (B3). It
generates walk clips with Wan 2.2 (B5), reads them onto the rig
in place as looping animations for review (B6), and delivers the approved ones to Unity as a Generic controller and
prefab played in Play mode (B7). This page documents the creature asset type, its rig, and the creature-motion provider the track will
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
  `max_rig_asymmetry` of the height across that bone: 0.05 for the `creature` type (owner ruling, 2026-10-27; a value
  per type). In the bounded check, the passing wolf seed mirrored within 0.005 and a failing seed 0.28.
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
- **`fit_bones`.** The manifest records the bones video2rig must fit (`rigging.fit_bones`): every named bone, and every
  `…End` bone that leads any skin (owner ruling, 2026-10-27), declared rather than left to the tool's auto rule. That rule drops bones leading under 0.4 % of the skin, such
  as a generated wolf's paws ([#139](https://github.com/gysahlgreene/SlopForge/issues/139)). Each bone's share of the
  skin is in its structure report.

The structure checks are structural evidence only. Deformation is judged by a person: `approve-rig --confirm` records
that review. It refuses a rig changed since it was made, a rig made from a model that was published again since, and a
rig whose lineage's output rights are `unknown` or `restricted`.

**Facing.** The head end is read from the highest skin. A creature whose tail stands above its head reads the wrong
way round. Its hind legs then seem to leave the body away from the root, so it is refused, with that reason. One case
is not refused: a rig that SkinTokens roots at the chest, on a creature whose tail stands above its head, would be named
back to front. The review poses show it, because the wrong leg lifts.

**Lighting and logs.** Every stage's identity carries the hashes of `blender/creature_rig.py` (with its helpers) and of
`slopforge/creature_rig.py`. Each seed's SkinTokens log is kept as `skintokens.log` beside its candidate. A creature is
published without lightmap UVs (`lightmap_uvs: false` in its type). It deforms, so Unity lights it with light probes,
and Unity's lightmap unwrap of a 57,000-face wolf aborted.

**Verified (2026-10-27):**
- Offline tests on a four-legged box fixture, and a local Blender test of the fixture through the check, the names and
  the finish.
- Live: a wolf generated through the `creature` type on the H100 at `final` (57,000 faces) was published and rigged
  three times with four seeds each. In every run seed 2 passed and was kept; 4 of 12 seeds passed overall
  ([evidence](media/creature-rig-b1-2026-10/README.md)).
- **SkinTokens is not reproducible per seed.** The same seed on the same model gave a different skeleton each run. A
  bounded run with PyTorch's deterministic mode (strict, cuDNN deterministic, cuBLAS workspace set) changed nothing:
  every repeat of seeds 1–4 differed (34 to 46 joints). The surface sampling uses the seeded global random state, so
  the source lies elsewhere and is not found yet. The seed is recorded, but it does not reproduce a candidate: keep
  the rejects, and do not expect a rerun to give the same rig.
- The kept rig's deformation awaits the owner's review.

The live gate runs a configured project's published creature:

```sh
SLOPFORGE_RUN_SKINTOKENS=1 SLOPFORGE_PROJECT_ROOT=<project> SLOPFORGE_CREATURE=<name> \
  python -m pytest -q -s tests/test_creature_pipeline.py -k external
```

## Views, training pictures and known motions (B2)

A rigged creature becomes a video2rig project with `creature calibrate`. Known motions are rendered through its cameras
with `creature synth`. Both run on the SlopForge machine, using the video2rig install configured below (local keys
only). They also run on a rig still awaiting deformation review, and `motion.rig_status` records which.

```sh
slopforge --project ~/UnityProjects/MyGame creature calibrate wolf        # --views a,b --widths w1,w2 --poses N
slopforge --project ~/UnityProjects/MyGame creature synth wolf random_s0 --kind random --seed 0
slopforge --project ~/UnityProjects/MyGame creature synth wolf gait --kind gait
```

**`creature.json`** is written from the rig record and the type, never from priors keyed to bone names
(`slopforge/creature_views.py`):
- `fit_bones` from B1 ([#139](https://github.com/gysahlgreene/SlopForge/issues/139)).
- Knees (`Shin`) and elbows (`Forearm`) as one-way `hinges`.
- For every other fitted bone but the root (`Hips`), `joints.<bone>.range`, from the type's `joint_limits` by role
  ([#140](https://github.com/gysahlgreene/SlopForge/issues/140)).

  The `creature` type declares video2rig's own bend limits for these names, since spike #129's exams ran on them, and
  `FrontPaw` 150, because the Khronos Fox's authored walk folds its front paws 148°. An end bone takes its chain's
  limit (`Tail3End`: `Tail`), else the type's `End` (45), for an end off a knee or elbow such as a dewclaw.

  **What a declared range replaces.** video2rig applies one range to a bone's bend, twist and sideways turn alike,
  replacing its per-channel priors for that bone. That includes a paw's one-way bend: it allowed 20° the wrong way,
  and a declared paw range allows the full range both ways. It also includes a toe's twist of 10° and the default
  twist of 69°. The training poses then include wider twists and some wrong-way paw bends. Whether that costs accuracy
  is for B3's exam to measure.
- A fitted bone without a declared limit refuses.

**The start frame** comes from video2rig's `render_start.py` with the creature's view pair, framing and declared
facing (#142). Passed as `--facing=-Y`, the facing is never guessed from foot and toe names:
- **Views.** The `creature` type uses `front,side`, the start frame B5's video route was proven from
  ([#149](https://github.com/gysahlgreene/SlopForge/issues/149)). In three-quarter + side, Wan 2.2 turned the creature in
  3 of 4 clips; in front + side with the split-screen prompt, in none. The three-quarter view reads a lifted front paw
  better, since a dead-front camera puts it in front of the hind leg (#140), so `three-quarter,side` is the choice
  (`--views`) for a creature whose motion does not come from video.
- **Widths.** The type declares a narrow front panel and a wide side panel (640 + 1280): a creature seen from the
  front needs little width. Without declared widths, render_start's one scale for both panels decides: the 1920 px
  frame is split by each view's span across its panel (three-quarter: 0.77 length + 0.64 width; side: the length), so
  neither panel wastes resolution.
- **Margins.** `margin` 1.4 and `margin_wide` 1.2 come from the type. render_start's orthographic height is the
  larger of the creature's height × `margin` and its length × `margin_wide` across the side panel. The scale decides
  whether video2rig's check passes:
  - At 1.45 the length margin framed the wolf 344 px tall; all four clips that reached the check failed it (body
    1.7–3.0 %, limbs 3.2 %).
  - At 1.2 the height margin frames it 400 px tall, as in #149; the same seeds and prompt passed (seed 2: body 1.2 %,
    seed 3: 0.9 %).
  - With 640 + 1280 panels and `margin` 1.4 (2026-10-30), the wolf is about 1.3× larger again. Seed 2 passed the
    check (body 1.37 %, limbs 0.92 %). The owner judged its fitted walk "significantly better but needs improvement"
    than the walk from equal panels at 1.8.

  Reader error is roughly fixed in pixels, so a smaller creature disagrees more as a share of its height. Scaling
  alone did not explain the failures, though: Wan may also draw a smaller creature's two views less alike. A larger
  creature barely raised the reader's confidence in Wan's front view (0.58 to 0.61–0.66).
- **Two views, two blind spots.** video2rig's `check`, and one step of its fit, need exactly two views. Each pair
  leaves part of a quadruped's walk unmeasured:
  - Front + side: the side view hides the far legs (confidence 0.19), and the front view shows their swing end on.
    The owner called the result "robotic".
  - Three-quarter (front-left, the only three-quarter render_start draws) + right side: no view measures the right
    legs' sideways place. The fit crossed the left and right paws in 34 of 109 frames (front) and 40 (hind), by up to
    33 cm; front + side crossed them in 2 of 109.

  The type keeps front + side, the pair the tool was designed for.
- **Check.** The calibration refuses a start frame from which any of the skin falls outside a panel.

**The reader's training pictures** are rendered with `reader.prepare --skip-train`: the type's `training_poses`, 3000.
Training them on the GPU provider is B3.

**A known motion** comes from `blender/synth_motion.py`, promoted from the spike's exam motion. It is seeded, and the
same seed writes the same file. Each kind starts at the start pose and keeps the skin on the floor:
- `random`: every fitted bone follows smooth noise, inside 0.9 of its declared range.
- `gait`: an in-place walk. Each leg swings from one bone (`Thigh`, `UpperArm`), its knee or elbow folds, and its
  paw and toes flex. The spine, neck, head and tail sway. A scapula and the end bones stay still: on B1's wolf,
  swinging the scapula as well kicked a front leg level, and curling the toes' end bones flicked them out of the
  frame (found by B3's exam, 2026-10-30).
- `action`: an authored action, looped.

A motion is checked channel by channel, as video2rig bounds a bone (its turns about X, Y and Z, intrinsic XYZ, each
within the range). A knee or elbow is checked against video2rig's own hinge limits. A motion past either is refused,
because exam v1 counts a result only when the truth stays inside the reader's ranges. Bad views, widths, kinds or
`--action` refuse before anything is made. The clip is rendered with video2rig's `render_poses.py` through the start cameras:
- each panel at its own size, one pose a picture;
- joined as render_start joins panels into `clips/<clip>.mp4`, at 24 fps unless asked otherwise (the exam asks for
  the rate clips are delivered at). A random motion and the gait keep their timing in seconds at any rate; an
  authored action is sampled key by key, so it is rendered at 24 fps only;
- with its truth (`exam/<clip>/labels.npz`, `poses.npz`, `truth.json`) and its frame times
  (`work/<clip>/timing.json`). Without them video2rig times a clip as 24 fps, so a 16 fps known motion compared
  only 64 of its 96 frames.

A motion whose joints leave a panel is refused.

## Reader training and the exam (B3)

The creature's joint reader is trained on the pictures calibration rendered, then examined on a motion SlopForge
already knows, before it reads any generated clip:

```sh
slopforge --project ~/UnityProjects/MyGame creature train wolf      # --steps 9000 by default
slopforge --project ~/UnityProjects/MyGame creature exam wolf       # --kind gait --seed 0 --frames 96 by default
```

- **Training (`detector_training`).** It runs video2rig's `reader.train` for the given steps. With
  `providers.video2rig.train_host` set, it runs on that machine:
  - the project goes to a fresh folder there with `rsync`. An earlier reader, clips, readings, fits and exams are
    not sent. rsync's SSH keeps the link alive, and a transfer that stalls for 10 minutes fails;
  - the runtime module is piped over SSH and trains with the host's own install, offline against the pinned
    backbone, as its preflight does;
  - `reader.pt` and `reader-train.json` come back, and the folder is removed whatever happened. If removing it fails,
    the log names the folder left on the host. Training stops after three hours (readers have taken 11 to 58
    minutes on an H100).

  Without a `train_host` it trains on this machine's CUDA card. The stage's parents are the training set calibration
  made (`reader/poses.npz`, `visible.npz`) as it is now. The training machine's install is checked before anything is
  sent, and its record (torch, device) is the stage's provider. It records the steps, the video2rig and DINOv2
  revisions, where it trained, the minutes and the held-out error per view. The held-out error is recorded, not gated: no limit
  is set. GPU training is not bit-repeatable, and the record says so.
- **Refused:** a creature not calibrated; a training set changed since calibration; an existing `reader/reader.pt`
  or `reader-train.json`. A reader is never replaced, because the clips and exams made with it name its hash, and
  training would delete the old report. Move both aside to train another.
  A failed training leaves no reader, since a partial one would pass for a trained one, and is recorded.
- **The exam (`reader_exam`).** It takes these steps:
  1. A known motion is rendered through the start cameras, as `creature synth` does (B2), at the rate the type's
     video graph delivers clips at: its one `CreateVideo` node's fps, 16 for Wan (`--fps` sets another). The clip
     is `exam_<kind>_s<seed>`, made once and reused by later readers' exams. A clip made with other frames, at
     another rate, or by another `synth_motion.py` than today's, is refused: a changed gait is another truth. Move
     its `exam/<clip>/` folder and `clips/<clip>.mp4` aside, and the next exam renders it again.
  2. video2rig's `check` and `run` read it with the reader. The reading is then fitted again as extraction refits a
     walk ([B6](#extraction-and-bake-b6)): with settings for that rate and within the walk's fit ranges. The exam
     judges that refit, the fit a delivered clip gets, and records it (`fit`: the rate, the settings and the
     ranges) in its stage identity and under the reader.
  3. `blender/exam_pose.py` poses the truth and the fit on the rig and reads back every bone's head and tail per
     frame, with the creature's height along up and its facing.
  4. `slopforge/creature_exam.py` measures them and judges exam v1's twelve limits (`EXAM_V1`; their definitions and
     the spike's numbers are in [#145](https://github.com/gysahlgreene/SlopForge/pull/145)). The swap rate leaves
     out the shoulder blades (the owner's ruling, 2026-10-30): on B1's wolf they sit close together and barely move.
     Their rate is recorded as `swap_shoulder_blades`, not judged.

  The reader examined is the one `creature train` last recorded; another reader put in its place is refused. The
  limb-end tips are each declared leg's last fitted bone. The reader names keypoints after bones (`FrontToes.L.tip` on
  the wolf), so the spike's filter on "Hand" and "Foot" in a label found none on a B1-named rig.
  - An exam counts only when every frame of the truth is compared and the truth matches the render's labels.
    Otherwise it is an error (recorded as `error`), not a verdict. A check that read no view disagreement fails
    those two measures.
  - A failed exam is an answer: it is recorded with every measure and the names of the measures past their limits,
    and `creature exam` exits 1.
  - The stage's parents are the reader and the known motion. Its outputs are kept per reader in `exam/<clip>/`:
    `exam-<reader>.json` (the verdict and every number), the posed frames, and copies of the fit and the check. The
    verdict is recorded per clip under the reader (`motion.reader.exams`).
- **Extraction needs a passed exam of the clip's fit.** `creature extract` counts only the exams that judged the
  clip's own fit: the settings for its frame rate and its motion's fit ranges. It refuses a reader with no such exam,
  with any such exam that did not pass (a pass on another seed does not outweigh a failure), or that is not the
  reader the exams saw. An exam of another fit, such as one at 24 fps or before the ranges changed, is not counted.
- **On the generated wolf (2026-10-30):** the reader trained on the H100 in 11.3 minutes (held-out median 5.6 px
  front, 4.07 px side, as the hand-trained reader's 5.6 and 4.04). Its exam passes 11 of the 12 limits, most with room
  (bone median 1.9°, worst body p95 9.5°, joint error 0.006 of the height), and fails the swap rate: 0.66 on the
  scapulae, while every limb pair is at most 0.033. The spike's rig had no scapulae. The gait's 3° chest sway parts
  the shoulders by up to 5.3 % of the height, and the fit reads that sway on the wrong side. The owner ruled that
  the swap rate leaves the shoulder blades out (2026-10-30).
  With the larger start frame (640 + 1280, `margin` 1.4), a newly trained reader examined at 16 fps with the walk's
  refit passes all 12 limits: bone median 2.0°, worst body p95 9.8°, joint error 0.008 of the height, detection 0.88
  side and 0.54 front, worst limb swap 0.056 (the shoulder blades 0.45, recorded). Its first run compared only 64 of
  the 96 frames: the known motion had no `timing.json`, so video2rig timed 16 fps as 24.
- **The port reproduces the spike.** On the spike's own data the measures match its `exam_compare.py` to 0.001: 471
  numbers on the wolf gait, and 365 on the Fox walk with the paw-range reader, the failing exam, detection and swap
  rate included. That data is private (the spike's working folder), so no repository test pins this match; the
  offline tests pin each measure on a three-bone fixture. `tests/test_creature_exam_blender.py` poses a known motion on the fixture quadruped as its own fit
  and reads no error, at the fixture's height and facing.

## Video generation and intake (B5)

A calibrated creature with a trained reader gets motion clips from its start frame with `creature video`:

```sh
slopforge --project ~/UnityProjects/MyGame creature video wolf walk            # --count N --seed S
```

- **Provider.** Wan 2.2 image-to-video in ComfyUI: `workflows/video_wan22_i2v_api.json`, #149's graph.
  - Two 14B fp8 experts, high noise to step 10, cfg 3.5, shift 5.
  - 1280×720 at 16 fps.
  - 121 frames took 1,300–1,600 s on an 80 GB H100.

  Its sidecar names the four model files, their SHA-256 and their output rights: Apache-2.0, cleared. The image
  worker runs it in its video mode (`--output video`): the start frame is bound to the graph's `LoadImage` node, the
  `SaveVideo` result is downloaded, and the worker waits up to an hour.
- **Prompt.** The prompt is the type's data, not code:
  - `video_motions.walk`: #149's split-screen continuous-walk prompt, its negative list, 121 frames, 4 retries.
  - `video_views`: how the prompt names each view of the start frame.

  `{subject}` is the asset's description and `{name}` its name. Front and side are #149's wording. The three-quarter
  line says "to its left", since render_start's three-quarter camera is always front-left. With it and a right side
  view, Wan held the facing on the first seed (2026-10-30), but the fit crossed the legs (see the start frame, B2).
- **Candidates.**
  - **Seeds.** Each try uses the next seed from `--seed`. The tries are the clips asked for plus the motion's
    retries (D6), decided by `failures.should_retry`.
  - **Records.** Every candidate is kept in `motion.videos.<motion>`: its seed, prompt, the provider's generation
    record, reasons and every intake number.
  - **Refused clips.** A refused clip stays in `clips/` with its `work/<clip>/intake.json`. An accepted one is
    registered in `motion.clips`.
  - **Faults.** A provider fault that is not a refusal, or an interruption, stops at once; the candidate is still
    recorded, as `failed`.
  - **Refused before any GPU time:** a missing reader, an uncalibrated creature, a start frame changed since
    calibration, video2rig not ready, ffprobe or ffmpeg missing, a graph without exactly one `WanImageToVideo` and
    one `LoadImage` node or not at the start frame's aspect, and any seed in the run's range already used.
  - **Stopping early.** The run stops early once the clips asked for are out of reach.
  - **Stage records.** The stage records the model files, the reader's SHA-256, the intake numbers and the check's
    result.
- **Reader.** The intake reads each clip's two views with video2rig's `check`, which needs `reader/reader.pt`. Train
  it with `creature train` ([B3](#reader-training-and-the-exam-b3)).

### Video intake

Fail-closed, before anything reads the clip (`slopforge/video_intake.py`). A clip that fails a check is refused with
its code, and the refusal is retryable. video2rig's check runs only on a clip that passed the first five.

The limits come from #149's 40 Wan clips, whose verdicts are known. On those clips the intake reproduces every
verdict: it refuses every turning, still and drifting clip and passes every clip that walked.

| Check (code) | Measure | Limit | #149's clips |
| --- | --- | --- | --- |
| Frame rate (`video_frame_rate`) | Share of frames that repeat the one before (a step under a tenth of the clip's large steps) | ≤ 0.05 | 0 on every Wan clip. A 24 fps clip in a 60 fps container repeats 60 % (fixture) |
| Frame 0 (`video_frame0`) | Mean difference of frame 0 from the start image, grey levels | ≤ 12 | 3.0–6.5 on all 40 |
| Presence (`video_creature_missing`) | Share of frames that show the creature (50 silhouette pixels or more), least panel; 0 if frame 0 does not | ≥ 0.98 | 1.0 on all 40 |
| Backdrop (`video_backdrop_drift`) | The backdrop's largest change in brightness from frame 0's, worst panel: a step and a steady drift alike | ≤ 11 | 1–6.7, and 10.7 on the one clip whose check still ran (e1). 11.7–23.7 where video2rig crashed (`IndexError` in its alignment), spun or misjudged |
| Motion (`video_still`) | Share of a panel's pixels moved from frame 0 (median over frames), least panel | ≥ 0.02 | Walking 0.048–0.30. Frozen clips 0.0016–0.0035; a side panel that stood still 0.009 |
| Facing (`video_turned`) | The outline's shape change: 90th percentile of the log change in width-to-height ratio, worst panel | ≤ 0.25 | Facing held 0.05–0.14. Turning 0.31–1.4 |
| Views (`video_views_disagree`, `video_limbs_disagree`, `video_check_failed`) | video2rig `check`'s body and limb disagreement, and its verdict; a check with no reading or that crashes on the clip refuses it | ≤ 1.5 % and 2 % of the height (D7) | The identity-swapped clip h1: body 1.65 % |

- **Identity drift is recorded, not refused.** The creature's colour against frame 0 (90th percentile, worst panel)
  was 7–27 on clips that kept the look and 79–94 where Wan redrew the wolf as a photo-real one (#149 variant h).
- **The clip's times.** The intake writes the clip's frame times, at its container rate, to `work/<clip>/timing.json`
  before video2rig reads anything. A clip that repeats frames is refused, so every frame is a frame of motion. Without that file video2rig assumes Seedance's cadences, reads Wan's 16 fps as 24, and the motion plays
  1.5× fast.
- **Not covered:**
  - **Cuts.** There is no check for a cut yet.
  - **Frame 0's difference is over the whole frame.** A creature that is small in the frame dilutes it.
  - **Drift under the limit.** It can still erode frame 0's silhouette: at 12 levels video2rig warned that the start
    pose covered frame 0 only 0.78.
  - **Steps.** video2rig's `steps` turns a walk on the spot into a walk forward. D9 delivers in place; B6 removes it.

## Extraction and bake (B6)

A clip that passed intake becomes a looping, in-place animation on the creature's rig:

```sh
slopforge --project ~/UnityProjects/MyGame creature extract wolf walk_s4
slopforge --project ~/UnityProjects/MyGame animation approve wolf walk_s4 --confirm   # after the review sheet
```

- **Extraction (`motion_extraction`).** video2rig's `run` reads the clip with the creature's reader and fits the rig.
  Only the reader road is used; a missing `reader.pt` is refused. The reading is then fitted again with
  `python -m video2rig.reader.fit <project> <clip> --tag=-slopforge`, because `run` fits with settings the project
  cannot change:
  - **Frame rate.** The fit's per-frame thresholds are tuned for Seedance's 24 fps. A Wan clip runs at 16 fps, so
    they are converted to the clip's rate (`video2rig.fit_settings`): at 16 fps `despike_deg` 6 → 9, `w_smooth`
    30 → 20, `lock_frames` and `lock_blend` 3 → 2, `bridge_max` 24 → 16 and `twin_switch` 6 → 4. `w_smooth` also
    weights three solves that stay near one frame's own pose (the floor bend, the self-pass and the foot lock); the
    conversion loosens those too, and the owner's chosen fit included that.
  - **The motion's ranges.** The reader trains on the type's wide `joint_limits`. A motion can fit within narrower
    ones (`video_motions.<motion>.fit_joint_limits`, by role, each above 0 and within the type's limit); the walk's
    are FrontPaw 90° and FrontToes 60°. An end bone takes its chain's, as it does for training. A project keeps its
    own copy of the type (`ai/asset_types/creature.yaml`): one copied before these ranges existed declares none, and
    fits within the training ranges (recorded as `fit_joint_limits: {}`) until they are added to it. The tool reads
    ranges only from creature.json and takes no option for them.
    The refit therefore sees the project through a temporary sibling folder (`.<project>-fit`): every entry is
    linked, and creature.json is replaced. The folder is removed afterwards.
  - **What it changed** on the generated wolf's walk (2026-10-30, the same reading): one-frame spikes smoothed
    131 → 89; median keypoint miss 5.68 → 5.53 px; the worst one-frame paw turn 107–118° → 78°. Front paw and toe
    turns over 30° in one frame fell from 32 to 24; the rest come from the toe readings, not from pinning the feet.
    Shown side by side, the owner chose this fit ("i think d is best yeah").

  The settings and ranges are part of the stage's identity. The refit (`out/<clip>-slopforge.npz`) is checked before
  anything bakes it:
  - its bones are creature.json's;
  - it has one fit per clip frame, at the intake's measured times (`timing.json`);
  - every number is finite.

  `motion.clips.<clip>.extraction` records the refit's median keypoint miss and its biggest one-frame turn of a bone
  (`biggest_turn`: degrees, bone, frame), measured by SlopForge on the refit. Neither is gated, since D8's limits are
  not set. Above 45° the turn is a warning in video2rig's own words. video2rig writes its summary report (outline
  match, frames under the floor, joints at their limit) only for `run`'s fit, which is not delivered. That report is
  kept as the stage's `report` file, not as the clip's warnings. Its outline match is not yet a usable measure on
  these clips: the side view reads 0.08–0.12 even on B3's rendered exam clip, where the fit is known to within 2°.
  The review sheet shows the frames.
- **Bake (`motion_bake`).** video2rig's `import_motion` puts the fit on the rig .blend as an Action at the clip's
  real times. `blender/bake_extracted_motion.py` then samples every key in world space, and
  `slopforge/creature_gait.py` measures:
  - **Plants per leg.** The foot is the lower tail of each declared leg's last two bones (B1's structure report). A
    swing passes 3 % of the height and plants under 1 %, measured from that foot's own resting height (its 10th
    percentile). On #149's g2 the fit sinks one foot 8 mm under the floor and the hind feet's lowest bone tails rest
    about 1 cm up, so a shared floor saw no hind plants at all.
  - **Full cycle and period.** A full cycle is every leg planting at least once, #149's plants per leg; `cycles` is
    the fewest plants of any leg. The period is the median interval between successive plants of one leg, over the
    legs that plant twice or more. A leg that plants only once is a warning (`weak_legs`): in #149's g3, g4 and e1,
    walks by eye, and the B5 framing test's seed 2, one hind leg lifts under 2.5 % of the height in most steps.
    Requiring two plants of every leg would have passed only g2 of #149's 18 imported walks. Refused, retryable
    (generate another clip), and kept with the fit:
    - a leg that never plants: `motion_no_cycle`;
    - no leg planting twice: `motion_no_period`.
  - **Stride.** The root's mean horizontal speed over the delivered window, times the period. This is the travel
    video2rig's `steps` reads into a walk on the spot.
  - **In place (D9).** The root's horizontal travel is removed: a least-squares cubic through its track, re-keyed
    in the root bone's own axes. g2's travel sped up from 20 to 29 mm a frame, so a straight line left the root
    surging 21 cm; the cubic leaves 5.5 cm and keeps the step's 6.6 cm sideways sway.
  - **Loop.** The most whole periods that fit, starting where the seam's pose matches best (mean bone angle,
    recorded as `seam_deg`, with the root's gap as `seam_root_m`). Both ends are keys on whole scene frames:
    import_motion keys a 16 fps clip on every 1.5 frames at 24 fps, and the FBX bakes whole frames, so a window between
    half frames exported one frame short with a worse seam than the one measured.
  - **Stance slide.** The median speed of planted feet once the controller moves the clip at its speed. A foot that
    stays where it was set down reads 0.

  Before measuring, the bake refuses an Action whose keys are not the clip's frames at its measured times; at
  video2rig's own cadence the period would be ⅔ of the truth and the Unity speed 1.5×. The armature is exported as
  `<clip>.fbx`, cut to the window, with the rig FBX's settings. It is registered as the candidate `animation.<clip>`
  with `loop: true`, `root_motion: false`, `stride_m`, `period_s`, `speed_mps`, `loop_periods` (the window's) and
  `min_plants` (the fewest plants of any leg), so the Unity Generic controller moves the creature at stride / period
  (B7). Its rights are the clip's model files,
  video2rig and Blender, plus the rig's lineage.
- **Review sheet (`review.png`).** One row per phase across one cycle (8 phases). Each row shows the clip's two
  panels at that frame beside the baked Action rendered through the same start cameras. The last row is the loop's
  seam: the window's last frame beside its first, as the game plays it.
- **Approval.** `animation approve` refuses:
  - without `--confirm`;
  - before the creature's rig is approved, or when the approved rig is not the one the clip was baked on;
  - when the FBX, bake report or sheet changed since the bake;
  - when the rights are not shippable.
- **Refused before any work:**
  - an uncalibrated creature;
  - a clip intake did not accept, or one changed since;
  - a missing reader or rig .blend;
  - a reader that has not passed the motion exam, or is not the reader the exam saw (B3);
  - creature.json or the start cameras changed since calibration;
  - a rig .blend other than the one calibration used: the start frame and the reader belong to that rig;
  - a clip extracted before (move its folder first).
- **Lineage.** The bake's inputs are the fit, the rig .blend, the clip and the start cameras (the sheet's crops and
  renders). Its provenance names the reader that made the fit.
- **Not covered yet:**
  - D8's limits on the fit report;
  - the foot-slide limit;
  - a cubic leaves some surge in a walk whose speed changes faster than it follows; the bake records the residual
    (`residual_travel_m`).

## Unity delivery (B7)

The approved rig and its approved clips go into Unity as a Generic Animator Controller and prefab:

```sh
slopforge --project ~/UnityProjects/MyGame animation unity-setup wolf
```

- **Refused before Unity runs:**
  - the rig not approved, or changed since;
  - a rig facing anything but -Y. Blender's -Y is Unity's +Z, where a game moves the creature, and nothing turns a
    creature rigged another way yet;
  - no approved clip (clips not approved are left out);
  - an approved clip whose FBX, bake report or sheet changed since its bake, or baked on another rig .blend;
  - a clip name that is not lower-case letters, digits and underscores, or a bake number that is not finite and
    positive. Both are written into the controller and the test script;
  - rights over the rig and the clips that are not shippable;
  - `--rig-type humanoid`: a creature is delivered Generic;
  - no Unity editor for the project's version (the Hub's, or `UNITY_EDITOR_PATH`);
  - a controller or prefab already in `<output_root>/Creatures/<name>/Unity/`.
- **The build.** One Unity run imports the rig and each clip as Generic without an avatar, with Preserve Hierarchy on
  both. The controller has one looping state per clip, named after the clip; the default is the first by name. The
  prefab's Animator has root motion off, because the clips are in place (D9).
  - **Speed (D9).** Each clip's walking speed is a float parameter `<clip>_speed`, in metres a second: the bake's
    stride divided by its period. A game moves the creature along its +Z at that speed (or scales `Animator.speed`
    to its own) and reads the value with `Animator.GetFloat`. No runtime script is added to the project.
- **Played before it is recorded.** Unity's test runner plays the prefab
  ([Unity projects](UNITY.md); the NUnit results stay beside it as `<name>_playmode.xml`).
  - **Facing and size:** in the bind pose the front feet lead along +Z, by more than 10 % of the height, and the
    mesh's height is within 5 % of the height B1 measured.
  - **Playing on its own:** the default state advances in real time, a bone turns, and the creature's own transform
    keeps its position, rotation and scale.
  - **Each clip:**
    - it loops;
    - its length is the bake's loop within one frame;
    - its speed parameter is the bake's;
    - every bone stays finite;
    - a bone turns more than 5° over the loop.
  - **In place:** over one loop the root bone must move, and its horizontal sway must stay under a quarter of the
    stride. A walk that kept its travel moves a whole stride every period. A root bone that never moves would pass
    vacuously, as every bone did before the binding fix below.
  - **Recorded, not gated (D9's foot-slide limit is open):** the stance slide once the creature moves along +Z at the
    clip's speed. The feet are each leg's last bone joint; the FBX has no leaf bones, so the paw tip is not a
    transform. The measures go to `<name>_playmode.jsonl` and the prefab's provenance.

  Each run first clears an earlier run's results and measures, so a run that never played cannot pass on them. A
  failed play removes the controller and prefab, keeps the results, and records the failed `unity_delivery` stage.
- **Found on the first live run (2026-10-30):** the bake exports the clip's armature alone. Unity folds a lone
  top-level node into the file's root, so the clip's curves were keyed `Hips/...` while the rig's bones sat at
  `Armature/Hips/...`. No bone moved, and the curves on the armature node landed on the prefab itself, turning it
  90° and scaling it 100 times. Preserve Hierarchy keeps both files' roots, so the clip's paths are the rig's. The
  builder is shared, so character clips get the same import. The playing-on-its-own check now fails a clip that
  moves the creature's own transform.
- **Recorded:** a `unity_delivery` stage. Its parents are the stage outputs that made the rig FBX (`rig_postprocess`)
  and each clip's FBX (`motion_bake`). Its outputs are the controller, the prefab, the results and the measures, each
  with its SHA-256. The stage also records the Unity editor version and the hashes of the builder and the tests. The
  controller and prefab are registered as candidate `unity.animator_controller` and `unity.creature_prefab`, pending
  review, with each clip's speed, stride and period, the play-mode results and the measures. Notices owed are
  written beside them.
- **Live gate:** `SLOPFORGE_RUN_UNITY_ANIMATION=1` bakes the fixture quadruped's keyed walk in Blender, builds it
  into a fresh Unity project and plays it (`tests/test_creature_unity_blender.py`). It needs Blender, the `unity`
  CLI and editor 6000.6.3f1 under the Hub or `UNITY_EDITOR_PATH`. It calls the builder and the Play-mode tests
  directly. `animation unity-setup`'s own wiring (the gates, the feet from B1's legs, B1's height, the root bone,
  the loop's length) is covered by offline tests only, because no generated creature is approved yet.
- **Not covered yet:**
  - a delivery of an approved generated creature: the wolf's rig awaits review, so its walk was played only as
    evidence, outside the gate ([evidence](media/creature-unity-b7-2026-10/README.md));
  - the foot-slide limit;
  - turning, blending between clips, and idles;
  - Windows.

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

With a `train_host` set, the client sends the project there for `reader.train` and brings the reader back
([B3](#reader-training-and-the-exam-b3)).

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
