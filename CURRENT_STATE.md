# Current state

## Objective

Finish integrating the verification baseline and the qualified M3 mask correction.
Next, finish the guided workflow through a newly generated Unity walk preview
(M4), before the model/detail quality phase (M5).

## Evidence and current work

- Root cause identified: `LoadImage` emits a transparency mask, while
  `ImageCropToMask` expects foreground. Automatic polarity guessing erased narrow
  subjects before inference. Broad subjects sometimes passed by accident.
- All four affected graphs now use explicit `InvertMask`; static and queue
  preflight reject the old connection. Generation retains `conditioning.png`.
- Actual ComfyUI loader/crop regression passes for narrow, broad, and RGB inputs.
- The failed input/seed, a fresh humanoid, and a full repeat have colored 4096²
  maps, resolved Blender texture references, FBX exports and four-view renders.
  The fresh model has three disconnected components; appearance defects remain.
- [Recovery evidence](docs/media/texture-mask-recovery-2026-10/README.md) records
  the first bad artifact, correction, reproducible inputs, seeds and limitations.
- Existing older Unity evidence is asset-specific. A new humanoid walk preview
  is not yet qualified. Prior humanoid test 3's recovered rig remains rejected.

## Completion gates

`make verify` and `make verify-live` have passed in development; rerun on the
integrated main checkout. Offline skips cover opt-in inference/rig/animation
checks; live verification explicitly exercises ComfyUI preflight and 2D/3D
inference. Neither establishes Unity playback or character approval.

The guided workflow implementation is still unmerged development work in the
registered worktree for `feat/guided-character-to-unity`; inspect `git worktree list`
before continuing it. Preserve that work when integrating focused fixes.

## Scope

Keep this pass focused on the material correction and verification structure.
Defer unrelated animation features, UI expansion, performance work, and model
quality experiments until their roadmap gates. Contracts describe required
behavior; full runtime enforcement and broad asset qualification remain incomplete.
