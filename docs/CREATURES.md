# Creatures

M5 (Creatures/Generic rigs) can generate a four-legged creature, rig it for review (package B1), and calibrate its
video2rig views and render known motions (B2). It generates walk clips with Wan 2.2 (B5), reads them onto the rig
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
- **Widths.** The type declares equal panels (960 + 960), as #149's clips had. Without declared widths, render_start's
  one scale for both panels decides: the 1920 px frame is split by each view's span across its panel (three-quarter:
  0.77 length + 0.64 width; side: the length), so neither panel wastes resolution.
- **Margins.** `margin` 1.8 and `margin_wide` 1.2 come from the type. render_start's orthographic height is the
  larger of the creature's height × `margin` and its length × `margin_wide` across the side panel. The scale decides
  whether video2rig's check passes:
  - At 1.45 the length margin framed the wolf 344 px tall; all four clips that reached the check failed it (body
    1.7–3.0 %, limbs 3.2 %).
  - At 1.2 the height margin frames it 400 px tall, as in #149; the same seeds and prompt passed (seed 2: body 1.2 %,
    seed 3: 0.9 %).

  Reader error is roughly fixed in pixels, so a smaller creature disagrees more as a share of its height. Scaling
  alone did not explain the failures, though: Wan may also draw a smaller creature's two views less alike.
- **Check.** The calibration refuses a start frame from which any of the skin falls outside a panel.

**The reader's training pictures** are rendered with `reader.prepare --skip-train`: the type's `training_poses`, 3000.
Training them on the GPU provider is B3.

**A known motion** comes from `blender/synth_motion.py`, promoted from the spike's exam motion. It is seeded, and the
same seed writes the same file. Each kind starts at the start pose and keeps the skin on the floor:
- `random`: every fitted bone follows smooth noise, inside 0.9 of its declared range.
- `gait`: an in-place walk.
- `action`: an authored action, looped.

A motion is checked channel by channel, as video2rig bounds a bone (its turns about X, Y and Z, intrinsic XYZ, each
within the range). A knee or elbow is checked against video2rig's own hinge limits. A motion past either is refused,
because exam v1 counts a result only when the truth stays inside the reader's ranges. Bad views, widths, kinds or
`--action` refuse before anything is made. The clip is rendered with video2rig's `render_poses.py` through the start cameras:
- each panel at its own size, one pose a picture;
- joined as render_start joins panels, at 24 fps, into `clips/<clip>.mp4`;
- with its truth (`exam/<clip>/labels.npz`, `poses.npz`, `truth.json`).

A motion whose joints leave a panel is refused.

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

  `{subject}` is the asset's description and `{name}` its name. Front and side are #149's wording; the three-quarter
  line is untried.
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
- **Reader.** The intake reads each clip's two views with video2rig's `check`, which needs `reader/reader.pt`. Until B3
  wraps training, train it with video2rig's `reader.train` on the GPU provider, as #149 did.

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
  Only the reader road is used; a missing `reader.pt` is refused. The fit (`out/<clip>.npz`) is checked before
  anything bakes it:
  - its bones are creature.json's;
  - it has one fit per clip frame, at the intake's measured times (`timing.json`);
  - every number is finite.

  video2rig's report (outline match, frames under the floor, joints at their limit, warnings) is recorded in
  `motion.clips.<clip>.extraction`, not gated: D8's limits are not set. The review sheet shows the frames.
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
  - no approved clip (clips not approved are left out);
  - an approved clip whose FBX, bake report or sheet changed since its bake, or baked on another rig .blend;
  - rights over the rig and the clips that are not shippable;
  - `--rig-type humanoid`: a creature is delivered Generic;
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
  - **In place:** over one loop, the root bone's horizontal sway stays under a quarter of the stride. A walk that kept
    its travel moves a whole stride every period.
  - **Recorded, not gated (D9's foot-slide limit is open):** the stance slide once the creature moves along +Z at the
    clip's speed. The feet are each leg's last bone joint; the FBX has no leaf bones, so the paw tip is not a
    transform. The measures go to `<name>_playmode.jsonl` and the prefab's provenance.

  A failed play removes the controller and prefab, keeps the results, and records nothing.
- **Found on the first live run (2026-10-30):** the bake exports the clip's armature alone. Unity folds a lone
  top-level node into the file's root, so the clip's curves were keyed `Hips/...` while the rig's bones sat at
  `Armature/Hips/...`. No bone moved, and the curves on the armature node landed on the prefab itself, turning it
  90° and scaling it 100 times. Preserve Hierarchy keeps both files' roots, so the clip's paths are the rig's. The
  builder is shared, so character clips get the same import. The playing-on-its-own check now fails a clip that
  moves the creature's own transform.
- **Recorded:** the controller and prefab as candidate `unity.animator_controller` and `unity.creature_prefab`,
  pending review, derived from the rig and the clips, with each clip's speed, stride and period, the play-mode
  results and the measures. Notices owed are written beside them.
- **Live gate:** `SLOPFORGE_RUN_UNITY_ANIMATION=1` bakes the fixture quadruped's keyed walk in Blender, builds it
  into a fresh Unity project and plays it (`tests/test_creature_unity_blender.py`). It needs Blender, the `unity`
  CLI and editor 6000.6.3f1 under the Hub or `UNITY_EDITOR_PATH`.
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
