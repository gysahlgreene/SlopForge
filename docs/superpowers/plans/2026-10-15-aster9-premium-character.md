# Aster-9 Premium Character Quality Implementation Plan
> **For agentic workers:** Use `superpowers:executing-plans` to execute task-by-task. Use the Pi/Qwen handoff skill for bounded Blender-automation writing when delegated, then have Codex/Luna review the change and resulting evidence. Do not use subagents. Steps use checkbox tracking. **Goal:** Produce a visually approved, structurally sound Aster-9 close-up hero candidate with convincing PBR materials and verified URP import. **Architecture:** Treat the current Pixal3D result as a retained blockout, refine geometry and materials in a new Blender source project, and keep all generated/intermediate candidate artifacts outside the public repository. Preserve the existing candidate and stop before rigging. **Tech Stack:** Blender 5.1, ComfyUI with user-run models only when separately authorized, PBR image maps, Unity URP. **Spec:** `docs/superpowers/specs/2026-10-15-aster9-premium-character-design.md`

## Global Constraints

- SlopForge remains MIT-licensed; do not bundle model weights, custom nodes, or third-party source assets.
- Use self-hosted inference; do not require a paid hosted inference service.
- Record exact model/node source and license status; unknown terms remain unknown.
- URP is the baseline. Do not claim project performance readiness without the actual target profile and budgets.
- Preserve original source files and the existing Pixal3D candidate; create a new review candidate.
- Do not submit another live inference without fresh explicit authorization.
- Do not rig until the user approves the exact visual/material candidate and structural readiness passes.
- Do not claim M0, SlopForge, or any category is complete or qualified from this asset.
- Pi/Qwen may write bounded Blender automation; Codex/Luna reviews scripts and resulting evidence independently. Do not use subagents.

## Review Focus

1. **Bad topology hidden by cleanup:** inspect boundaries, non-manifold edges, and connected components before and after each mesh operation; do not weld/remesh away visible design detail to make counts pass. Pin in Task 2's before/after inspection report and visual comparison.
2. **Concept drift across views:** compare the front, left, and rear guides before adding detail; stop and record any inconsistent source reference rather than inventing unseen design features. Pin in Task 2's angle-by-angle review sheet.
3. **High-resolution but low-quality maps:** a 4096 map or linked image node does not pass on its own; inspect UV coverage, close-up sharpness, material boundaries, and each map channel. Pin in Task 3's map contact sheet and channel checks.
4. **Placeholder or incorrect normal map:** require a non-placeholder tangent-space normal map, correct color-space/import handling, and a close-up render that shows the detail without seams or black artifacts. Pin in Task 3's normal-map checks and URP preview.
5. **Unverified dependencies or target settings:** do not call the stack open-source or performance-ready when a model/node license, Unity profile, or budget is unknown. Pin in Task 1's provenance record and Task 4's qualification summary.

## File Map

- Read only: `Downloads/Aster-9-Character-Review/Aster-9-Review-Candidate/Concept/{front,left,back}.png`, its `README.md`, and its existing candidate artifacts.
- Read only: the existing Pixal3D run directory, represented during execution by `PIXAL3D_RUN_DIR`, containing `aster9_pixal3d_candidate.glb`, `generation.json`, `inspection.json`, and native maps.
- Create outside Git: the new `Aster-9-Premium-Review-Candidate/` directory alongside the existing Aster-9 review bundle. Set `ASTER9_REVIEW_ROOT` to this new directory and create `Source/`, `Geometry/`, `Materials/`, `Previews/`, and `Evidence/` under it.
- Create outside Git: `Geometry/Aster-9-Premium.blend`, the final GLB, baked PBR maps, close-up review images, structural reports, and a README with hashes and dependency/license provenance.
- Do not modify SlopForge production code or publish private candidate assets in this plan. If a shared pipeline defect is found, record it and stop for a separate scoped plan.

## Task 1: Preserve inputs and establish the candidate baseline

**Files:** Read the concept set and Pixal3D artifacts above. Create `Evidence/baseline.md` and retain copies under `Source/` in the new candidate directory.

**Inputs:** Existing three concept views, the 2026-10-15 Pixal3D GLB and its metadata/maps, current workflow requirement sidecar, and installed ComfyUI model/node facts if they can be read without queueing work.

- [ ] Create the new review directory without overwriting the existing review candidate or run artifacts.
- [ ] Set `ASTER9_REVIEW_ROOT` to the new candidate directory and `PIXAL3D_RUN_DIR` to the existing run directory. Confirm neither points into the current review candidate or a directory that will be cleaned up.
- [ ] Copy the three concept views, source GLB, generation metadata, inspection report, and original maps into `Source/`; record SHA-256 for each copied file and confirm the copied hashes match.
- [ ] Record current inspection facts: 26,191 vertices, 29,888 faces, 10 components, 11 boundary edges, 288 non-manifold edges, 4096² base-color/roughness/metallic maps, and 1×1 neutral normal map.
- [ ] Read the workflow sidecar and record each exact model filename/hash/license source plus each required custom-node source/revision. Verify upstream license statements for the exact model artifacts where possible; if verification is unavailable, record `unknown` and do not claim the stack is fully open source.
- [ ] Do not submit inference during preflight. If a fresh candidate becomes necessary, stop before queuing it and request separate authorization.
- [ ] Render or inspect the retained Pixal3D candidate against the front, left, and rear concepts; write `Evidence/baseline.md` with the specific silhouette, proportion, missing-detail, texture, and topology gaps visible from each view.

**Deliverable:** A new, immutable source bundle and an evidence-backed baseline that identifies what geometry and material work is needed.

## Task 2: Refine geometry against the approved views

**Files:** Create `Geometry/Aster-9-Premium.blend`; retain any Blender automation used for the asset under `Geometry/`; export a review GLB there.

**Interface:** The original Pixal3D GLB remains the source reference. The task produces a separate Blender source and GLB that preserve Aster-9's approved silhouette and concept details. Do not edit the original candidate in place.

- [ ] Import a copy of the Pixal3D candidate into a new Blender file and organize the body, flexible suit, visor, and rigid equipment into named collections/material regions; retain a hidden source collection for comparison.
- [ ] Classify every disconnected component and topology warning as intentional, repairable, or unresolved in `Evidence/geometry-review.md` before changing the mesh.
- [ ] Preserve the candidate's recognizable primary silhouette; repair local damaged areas and rebuild suit forms only where the multi-view comparison shows a defect. If the body silhouette cannot be corrected without replacing most of the generated body, stop and report that a fresh authorized model source is needed.
- [ ] Avoid folds or surface artifacts that read as melted geometry in close-up views; do not smooth the whole mesh to hide defects.
- [ ] Model sharp, silhouette-changing suit hardware and panel layers as geometry. Reserve fine fabric weave, stitching, and shallow wear for texture or normal detail so they do not distort the silhouette.
- [ ] Keep accessory pieces separate only when their distinct shape/material or later deformation justifies it; identify every intentional separate component in the review notes.
- [ ] Rebuild/repair UVs only after geometry is stable. Verify islands cover the intended material regions, avoid unintended overlap, and leave bake padding between islands.
- [ ] Save the Blender source before export. Export a separate GLB and inspect it with the repository inspector:

```bash
"$BLENDER_BIN" --background --python blender/inspect_model.py -- \
  "$ASTER9_REVIEW_ROOT/Geometry/Aster-9-Premium.glb" \
  "$ASTER9_REVIEW_ROOT/Evidence/geometry-inspection.json" \
  1000000
```

- [ ] Treat the inspector's large face budget as a diagnostic ceiling only; do not claim performance readiness from it. Resolve every unexplained boundary/non-manifold warning and every detached debris component; visually verify intentional parts rather than merging them indiscriminately.
- [ ] Render front, left, rear, three-quarter, helmet/chest, glove, and boot close-ups. Compare to the concepts before proceeding. If the shape still fails the close-up target, retain the result and report the first failing view instead of hiding it with texture.

**Deliverable:** A separate Blender source and geometry candidate with resolved or explicitly explained structural findings and review views.

## Task 3: Author and validate the PBR materials

**Files:** Create `Materials/basecolor.png`, `normal.png`, `roughness.png`, `metallic.png`, and `Evidence/material-review.png`; update material nodes in `Geometry/Aster-9-Premium.blend` and re-export the GLB.

**Interface:** Materials are authored on the final mesh UVs. Use Blender procedural materials or external textures with verified, recorded terms; do not depend on a paid texture-generation service or unknown-license texture packs.

- [ ] Define separate material regions for suit fabric, reinforced fabric/rubber, hard polymer, metal hardware, visor, and glass/emissive elements where the concept supports them.
- [ ] Keep base color free of baked lighting. Give roughness and metallic maps values appropriate to each material region; do not treat cloth or rubber as metal.
- [ ] Create and bake a real tangent-space normal map with visible but restrained weave, seams, and micro-surface detail. Do not export the 1×1 neutral placeholder as the finished normal map.
- [ ] Use 4096² as the close-up authoring resolution for this candidate, preserving uncompressed source maps. Do not claim a runtime texture-memory budget until a target project profile is supplied.
- [ ] Check each map's dimensions, color-space interpretation, channel use, UV alignment, padding, and mesh identity. Inspect the normal map as a normal, not as sRGB color.
- [ ] Render neutral-light material close-ups at helmet, chest, sleeve, glove, knee, and boot. Reject visible seams, blur, projection smearing, random surface blotches, and material regions that collapse into one glossy response.
- [ ] Re-export GLB and verify each material references the correct map, no references are missing, and the copied source/texture hashes are recorded in `Evidence/material-review.md`.

**Deliverable:** A coherent, sharp PBR set visibly differentiated across the suit and linked to the exact final mesh.

## Task 4: URP review and user approval

**Files:** Create `Previews/` review images and `Evidence/final-review.md`; preserve the final Blender source and exported GLB/maps in the candidate directory.

**Interface:** Review the same candidate identified by recorded hashes. Use the user's URP Unity project if available; otherwise use an isolated URP preview project only for import/material checks, and make no project-performance claim.

- [ ] Import the exact final GLB and maps into URP. Verify the Lit material, base color, metallic/smoothness, normal map, alpha/visor behavior, and intended color-space settings.
- [ ] Render or capture the same front, left, rear, three-quarter, and close-up views in neutral Blender lighting and in URP. Record Blender and Unity versions, render pipeline, map sizes, and any interventions.
- [ ] Review visual fidelity, silhouette, folds, hard-surface edges, material separation, texture sharpness, UV artifacts, and all remaining geometry warnings. Keep visual/material approval pending until the user makes a decision on the exact candidate.
- [ ] State structural, visual/material, Unity import, performance, deformation, and runtime results separately. Mark unknown target-performance requirements and unrun gates explicitly.
- [ ] Stop before rigging. Only after the user approves the exact visual/material candidate and readiness evidence passes should a separate rig/deformation plan begin.
- [ ] Update issue #14 with the exact candidate/artifact hashes, evidence, decision, and remaining limits after review; do not close it while user approval or required gates remain open.
- [ ] Write the candidate `README.md` with reproduction steps, source and output hashes, Blender/Unity/ComfyUI facts, model/node license status, review decision, and every unchecked gate.

**Deliverable:** A reviewable URP candidate with reproducible source/maps, evidence, and an explicit user approval decision or a documented rejection/follow-up.

## Completion checks

- [ ] Confirm the original source candidate and run artifacts are unchanged.
- [ ] Run the Blender inspector on the final export and inspect the complete report; explain every warning:

```bash
"$BLENDER_BIN" --background --python blender/inspect_model.py -- \
  "$ASTER9_REVIEW_ROOT/Geometry/Aster-9-Premium.glb" \
  "$ASTER9_REVIEW_ROOT/Evidence/final-inspection.json" \
  1000000
```
- [ ] Compare all review views and maps against the approved concepts; do not use automated counts as a substitute for visual review.
- [ ] Verify the exported GLB in URP or record the concrete environment blocker. Keep performance, rigging, deformation, Unity playback, and pipeline qualification unclaimed unless separately evidenced.
- [ ] Confirm the repository has no generated Aster-9 binaries, local machine reports, or unverified dependency artifacts added.

## Execution Notes

This plan changes an asset, not shared SlopForge production code. Do not run the full test suite unless implementation expands into repository code. If a shared code change becomes necessary, stop and write a separate bounded plan with focused tests. A fresh live inference is not included: the prior authorization covered one run, which is complete.
