# Character source geometry quality system

## Status and scope

Design proposal for a follow-up to the existing character-generation and
rigging work tracked by [issue #14](https://github.com/gysahlgreene/SlopForge/issues/14).
This work is queued behind the active M0 core-reliability and preceding category
gates; it does not reorder the roadmap. It concerns repeatable character source
quality in SlopForge, not completion or approval of the external Aster-9 asset.

No production implementation, new character inference, or rigging is authorized
by this design. A later implementation plan may prepare offline evidence and
workflow contracts. Any new ComfyUI/Pixal3D submission requires separate user
authorization.

## Problem

The current `character_3d_pack` produces one full-body neutral-pose concept and
passes the selected concept to the configured 3D workflow. Existing structural
inspection can expose components, boundaries, non-manifold edges, UVs, and map
links, but these checks do not show whether the generated surface contains the
designed forms or matches the approved views. Character operation guidance
already requires neutral multi-view inspection, yet the character route does not
define a reusable source-quality review record or a representative evidence set.

The Aster-9 failure case demonstrates the distinction. Its approved front, side,
and rear concepts contain shaped helmet, harness, chest, joint, glove, knee,
boot, and backpack details. Its geometry-only renders show a soft blockout with
missing modeled forms and visible surface artifacts. High-resolution PBR maps
cannot create those forms. Its topology warnings also cannot be explained by
aggregate counts or indiscriminate cleanup. This is evidence for a workflow gap,
not proof that one inference backend or resolution setting is the root cause.

## Goals

- Make concept-to-source-character review reproducible across front, side, rear,
  three-quarter, and required close-up views.
- Preserve the selected concepts, generated mesh, processing settings, maps,
  review renders, and decisions as hash-linked candidate evidence.
- Keep geometric form/detail review distinct from material appearance and
  structural checks; do not allow texture quality or structural counts to imply
  visual approval.
- Require every topology warning and disconnected component to be classified
  as intentional, repairable, or unresolved before a candidate can pass its
  applicable structural gate.
- Keep human visual/material approval attached to the exact candidate and its
  artifact hashes.
- Compare workflow options using known evidence and verified provenance, while
  keeping unobserved model/node identity and licensing facts `unknown`.

## Proposed system behavior

1. A character source review package records the approved concept set and hashes,
   the selected generation input(s), effective workflow/settings, raw and
   prepared mesh identities, PBR map identities, inspection results, and rendered
   review views. If a route accepts only one image, the record says so; it must
   not imply multi-view conditioning.
2. The package contains aligned front, side, rear, and three-quarter renders,
   plus close-ups selected from concept-critical regions. View labels and camera
   directions are explicit so reviewers can compare like with like.
3. Structural findings and visual findings remain separate. Structural reports
   enumerate warnings and component bounds for inspection. Visual review records
   concept fidelity, missing or malformed forms, silhouette, and close-up defects.
4. A candidate with missing designed geometry cannot pass by adding material
   maps. Material review begins after the source mesh and UV identity are fixed;
   maps and renders reference that exact mesh.
5. Rejected or failed candidates and their diagnostics remain available. Changes
   to the selected concept, source mesh, processing result, or material set make
   affected evidence stale without erasing its history.
6. Rigging remains downstream of explicit source approval and structural
   readiness. This work makes no deformation, animation, performance, runtime,
   or workflow-qualification claim.

## Design choices

### A. Tune the current generation route only

Change prompts, image conditioning, model resolution, or repair settings and
compare the result. This is the smallest technical change, but the Aster-9
evidence does not identify which setting caused the missing forms. Resolution
and topology cleanup could cost more compute or hide damage without adding
concept detail.

### B. Add an evidence-first character source-quality stage — recommended

Define a character-specific review package and gate around the current recipe and
existing backend boundary. First establish comparison criteria and run an
offline evaluation of retained candidates. Document candidate multi-view routes
and their provenance/licensing limits; only test a route with live inference
after separate authorization. This makes the current limitation visible before
selecting or integrating a generator.

### C. Build a deterministic Blender reconstruction route

Create concept-derived geometry as a dedicated character authoring stage. This
offers more direct control over designed panels and topology, but it is a large
new modeling workflow with its own scope, authoring tools, and deformation risks.
The current evidence does not establish that it is preferable to an improved
generation route.

## Recommendation

Proceed with B as a bounded M4 follow-up. Use Aster-9 and other retained
character artifacts as diagnostic cases, not as a qualification sample. The
first implementation package should define the evidence format and offline
review procedure, then report which route questions remain unanswered. Do not
select a new backend, change production prompts/settings, or claim a quality
improvement until a separately authorized comparison provides evidence. If
existing routes cannot meet the reviewed geometry target, return with the
evidence and a separate design for C.

## Acceptance criteria for the future system work

- The source review package is reproducible from its recorded candidate and
  concept hashes and contains the required aligned views and close-ups.
- An offline fixture demonstrates that visual approval cannot be inferred from
  structural pass, material approval, export success, or `ready` state.
- Each reported component/topology issue is traceable to inspectable geometry
  evidence or remains explicitly unresolved; aggregate counts are not presented
  as a diagnosis.
- The review record distinguishes visual, structural, material, deformation,
  and Unity/runtime gates and ties any human decision to the exact artifact set.
- Failure and rejection preserve inputs and evidence and invalidate only affected
  downstream decisions.
- Documentation states that the current single-image route is single-image,
  records generation/model/node provenance limits, and keeps unknown license
  terms as `unknown`.
- `make verify` passes for any eventual production implementation; live inference,
  visual approval, deformation, Unity playback, and qualification are reported
  only when separately performed under declared criteria.

## Non-goals

- Improving or replacing the external Aster-9 candidate in this system design.
- Submitting inference, installing models/nodes, or bundling third-party weights.
- Rigging or claiming Aster-9 visual/material approval.
- Automatically scoring artistic quality or replacing human appearance review.
- Using aggressive remeshing, welding, or smoothing to hide topology defects.
- Reordering M0–M4, qualifying humanoids from Aster-9 alone, or changing shared
  production code before a reviewed implementation plan.

## Contract alignment

The product contract requires the asset's project context and concept to remain
the source of truth, and reserves appearance approval for a human. The pipeline
contract requires retained multi-view evidence, stage identity, explicit review
state, safe invalidation, and preservation of failed candidates. The quality
contract keeps visual, structural, material, deformation, performance, and
runtime findings separate and forbids qualification without declared criteria.
These peer contracts align on the proposed gate separation; no conflict was
identified for this scope.

The roadmap keeps M0 Core Reliability active and places Humanoids at M4 after
props, modular environments, and weapons/mechanical assets. This design records
backlog direction only; it does not change that order.
