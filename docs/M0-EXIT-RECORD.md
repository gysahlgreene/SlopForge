# M0 core reliability: exit evidence record

Prepared 2026-10-21 against the [roadmap](../ROADMAP.md)'s M0 exit evidence. **The project owner closed M0 on
2026-10-21** on this record, within the scope below, after rating the v5 runs better than v3. This record does not qualify any
category, and Qualified stays out of scope.

**Scope of the claim:**
- static props (`prop` type);
- compute profile `h100`, tier `final`;
- ComfyUI 0.37.0 on one H100 80 GB;
- local Blender 5.1.0, Python 3.14.7 and Unity 6000.6.3f1 with URP 17.6.0 on macOS arm64.

Other categories, profiles, tiers and platforms are not covered.

## Exit items

### 1. A documented clean starting state, with actionable preflight failures

**Evidence:**
- [Installation](INSTALL.md), [setup](SETUP.md), [Unity delivery](UNITY.md) and the
  [compute profiles](COMFYUI.md) document the starting state.
- Every protocol run started from a fresh copy of the URP blank project plus `slopforge init`. Each record
  lists the tool versions, workflow versions and settings used.
- Owner-declared prop requirements and thresholds ship in `templates/asset_types/prop.yaml`: at most 5 parts,
  plus the colour check.
- These checks stop with an actionable error before expensive work:
  - `doctor`;
  - the workflow requirement sidecars, checked against `/object_info` by `make verify-live`;
  - the Unity project and CLI preflight;
  - the emitter preflight, which fails as `configuration` before any mesh inference.

**Gaps:**
- ComfyUI does not expose model weight hashes or custom-node revisions, so they are recorded as unknown.
- The H100 service stops when its last login session closes. It needs a held session; that is documented,
  not automated.

### 2. Brief → concept/selection → conditioning → geometry → mesh/UV → materials → multi-view review → explicit approval → Unity import/preview, with stage identities, provenance and retained artifacts

**Evidence:**
- **Protocol runs:** criteria [v1](media/props-provisional-2026-10/README.md),
  [v2](media/props-provisional-2026-10-v2/README.md), [v3](media/props-provisional-2026-10-v3/README.md),
  [v4](media/props-provisional-2026-10-v4/README.md) and [v5](media/props-provisional-2026-10-v5/README.md).
  - 30 runs on `h100`/`final`, each from brief through concept selection, conditioning, geometry,
    mesh/UV, materials, four Blender review views plus a turntable, and a Unity URP import with a
    four-view render.
  - Every stage has a manifest record with content-addressed inputs and outputs, and the run folders are
    kept.
- **Explicit approval and publication:**
  - A 2026-10-20 live check (private): `approve-texture` published an H100 prop into a fresh URP project
    with 16 published artifacts, and Unity assigned the material with its four textures.
  - The opt-in Unity identity test (`SLOPFORGE_RUN_UNITY_IMPORT=1`, #74) shows that replacing, reimporting
    and renaming keep or separate GUIDs as intended, and that a prefab follows a republished mesh.

**Gaps:**
- The protocol does not permit `approve-texture`, so publication is shown on one live asset plus the
  Unity fixtures.
- There is no Play mode or in-scene check: Unity renders are editor batch renders.

### 3. Controlled failures stop dependent work; rejected candidates survive; resume reuses valid stages and invalidates affected downstream results; interventions are supported steps

**Evidence:**
- Packages 1–3 provide failure classification, bounded retries, safe resume, invalidation and lineage, all
  with deterministic tests.
- Live cases:
  - An interrupted H100 run resumed with no new inference, reusing conditioning and mesh stages (2026-10-20).
  - A ComfyUI outage was classified `environment` and resumed once (v1 C2).
  - A conditioning crash stopped the run and kept it (v2 B2). It was fixed with a regression test.
  - Three candidates failed the colour check, were retried, and were kept (v4 B2).
  - A lost ComfyUI job was interrupted and resumed once (v5 C1).

**Gaps:**
- When ComfyUI restarts, its queued jobs are lost, but the CLI keeps waiting until its deadline. In v5 C1 it
  was interrupted by hand.
- Output downloads are not retried; one experiment run was lost to a download timeout.

### 4. The original texture-mask failure and fresh representative inputs stay covered; structural and appearance results stay distinct

**Evidence:**
- The [texture-mask recovery](media/texture-mask-recovery-2026-10/README.md) report and its regression
  tests remain in `make verify`.
- Every protocol record reports structural, technical, Unity and visual results separately.
- Owner visual reviews are recorded as owner decisions, separate from the machine checks.

**Gaps:** appearance is judged by the owner and by one automated colour measure. No other appearance
measure is declared.

### 5. Three representative briefs, two independent runs each, recording failures, interventions, versions and unchecked gates

**Evidence:** the qualification records above. Each was committed before its runs, and each lists its
criteria, permitted interventions and unchecked gates.

| Criterion | Runs passing every stage | What the set showed |
| --- | --- | --- |
| v1 | 1 of 6 | Concept adherence (crate proportions and straps, jug view) and lantern emitters |
| v2 | 5 of 6 | An exit crash in background removal (fixed) |
| v3 | 6 of 6 | One jug baked teal; no threshold measured colour |
| v4 | 5 of 6 | The colour check measured hidden surfaces (fixed) |
| v5 | 6 of 6 | Colour judged from the concept's side; one permitted resume |

The owner rated v1 better than the 60% baseline, v2 better than v1, v3 better than v2 (naming colour
accuracy as important), and v5 better than v3. The v5 set is Provisional for its scope.

**Gaps:** two runs per brief cannot measure a failure rate.

### 6. `make verify` passes with skips reported; authorized live checks and human/Unity evidence cover the claimed scope

**Evidence:**
- `make verify`: 722 passed, 8 skipped. The skips are opt-in tests: live ComfyUI, Unity, SkinTokens and
  Blender rig smokes.
- `make verify-live` on 2026-10-21, against the H100: 3 passed with 9 subtests in 70 s. That covers every
  bundled workflow checked against `/object_info`, plus the live image and 3D integration tests.
- Live inference evidence comes from the protocol runs and experiments.
- Human review evidence comes from the owner's reviews of v1–v3.

**Gaps:** none beyond those listed per item.

## Unchecked gates (do not count as passes)

- Performance beyond the declared budget (30k triangles, one material, 4096² maps): LOD and collision.
- Play mode, in-scene lighting, and scene scale and pivots.
- Style consistency across a project.
- Fidelity of unseen sides beyond the review renders.
- Other categories, profiles, tiers and platforms.

## Known limits carried into M1

- The crate's wood comes out paler than its concept on every seed (the colour check passes it).
- Colour drift in a small part is not checked, because only the dominant colour is compared.
- Jug ribbing shows in Unity.
- A crate's open top can be reconstructed closed.
- Glass and transparent parts (#44).
- Invented hidden sides (#63).
- A lost ComfyUI job is not detected (fixed after closure, issue #76).
- Output downloads are not retried (fixed after closure, issue #76).

## Decision

Every M0 exit item has evidence within the scope above, and the gaps are listed against each item. On
2026-10-21 the owner closed M0 Core reliability (epic #26) and made **M1 Props** the active milestone,
carrying the limits above into it.
