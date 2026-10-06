# 3D-only product design

## Intent

Refocus SlopForge on producing coherent 3D game assets, including characters that can be prepared, rigged, deformation-reviewed, animated, and imported into Unity. The existing worktree contains active 3D and rigging changes that must be preserved.

## Product boundary

Keep the user-facing path for 3D props, collectibles, characters, environment kits, mesh cleanup and readiness, rigging, skeletal animation, provenance, candidate review, recipes, and Unity export. Keep concept and material image generation only as supporting inputs to 3D workflows. A 3D recipe remains the way to coordinate a related asset set.

Remove shipped 2D output capabilities: sprite generation and packaging, UI packs, VFX packs, tilesets and their Unity import helpers. Remove the generic prototype planner, which composes content recipes without a qualified concept-to-plan implementation. Do not remove the general recipe runner or 3D environment validation.

Remove those lanes from the CLI, default initialized taxonomy and recipes, product documentation, package modules, and tests that exclusively exercise removed behavior. Do not delete the historical ecosystem research, sprite benchmark evidence, generated evidence, or existing user project data. Existing custom taxonomy definitions are not migrated or deleted; the bundled product surface simply stops shipping these 2D types and commands.

## Preserved architecture and constraints

- Keep the local/remote HTTP ComfyUI service abstraction and provider-specific workflow isolation.
- Keep concept/reference libraries, provenance, candidate approval, quality tiers, resumable recipes, Blender processing, Unity model/material tooling, and 3D character normalization/readiness/rigging/deformation/animation work.
- Keep image generation only for 3D concept and material inputs; this is not a promise of general 2D asset production.
- Rewrite the README and active user docs to describe the actual 3D route and current qualification limits. Do not describe generated character rigs as production-ready without visual deformation and Unity playback evidence.
- Preserve all pre-existing dirty work. Do not touch `main`, push, or remove historical research artifacts.

## Implementation and validation

Apply the cut surgically across CLI dispatch, package modules, initializer templates/directories, packaging metadata, and product docs. Remove tests whose only contract is a retired lane; preserve shared tests for image-as-input, review, provenance, recipes, and 3D workflows. Do not run the test suite during this pass. Validate the resulting CLI surface and source references with non-test smoke/static checks, and report remaining unqualified 3D stages explicitly.
