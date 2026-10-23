# Modular environment kits: qualification record, criterion M2-v1

Declared on 2026-10-22, before any protocol run, under the owner's M2 decisions recorded in issue #94. Results go
in the [evidence report](README.md). Six runs cannot make anything Qualified; at most they make kits Provisional for
the tested scope.

## Scope

- **Kits** (`templates/recipes`), two independent runs each:
  - `stone_ruin_kit`, with layout `courtyard`;
  - `timber_house_kit`, with layout `room`;
  - `scifi_corridor_kit`, with layout `room`.
- **Environment:** compute profile `h100`, quality tier `final`. Each run starts from a fresh copy of the Unity
  6000.6.3f1 / URP 17.6.0 blank project.
- **Code:** one fixed SlopForge commit for all runs, recorded per run.

## Procedure, per run

1. `slopforge init`, then `recipe run <kit> --name <run>`.
2. The agent selects one concept per module, for evaluation only. It records the reason for each pick, judged
   against:
   - the module's brief;
   - a face close to the module's declared shape (square for walls);
   - the inside view of the L for corners.
3. The stone kit only: approve its `stone` texture, the shared kit material, first.
4. For each module: `approve <module> <concept>`, then `approve-texture` with its lowest-numbered valid material
   candidate.
5. `environment-check <run>`.
6. `environment-scene <run> <layout>`, which saves and renders the assembled Unity scene.

**Permitted interventions** (each recorded):
- **After an infrastructure interruption** (a lost or restarted remote job): one `approve --resume`.
- **After a `module_stretch` stop:** one fresh selection of a different concept for that module. This is the
  remedy the stop asks for.

## Criteria (owner-accepted 2026-10-22)

A run passes when every module and the assembled scene meet all of these.

| Gate | Criterion | Where it is measured |
| --- | --- | --- |
| Size | Each declared `target_size` axis within 0.05 m | `environment-check` (grid, max dimension) and validation dimensions |
| Pivot | Each module's origin at its declared pivot within 0.05 m | `environment-check` |
| Stretch | Face stretch at most 1.3 | validation `axis_stretch`; `environment-check` |
| Corner shape | The emptiest footprint quarter at most 0.15 | validation `open_quadrant`; `environment-check` |
| Joints | Corner arms within 0.05 m of the declared thickness | `environment-check` |
| Concept fit | At least 0.8 | validation `concept_fit` |
| Colour | Hue difference at most 4 and chroma ratio at least 0.6, against a coloured concept (near-grey concepts are not checked) | validation |
| Budgets | Faces within each module's declared budget; maps at its declared size (2048²) | validation; `environment-check` budgets |
| Unity | Every module stands at its placement height (0.05 m), has a mesh collider and is static; no seam gap wider than 0.05 m; the scene builds and renders | `environment-scene` report |
| Matching look | The stone kit's modules take their base colour from its approved kit texture | the kit material stage |

## Unchecked gates

Not checked by this protocol, and reported as open:
- the owner's visual approval of the assembled scenes, which is reviewed after the runs;
- Play mode;
- lightmapping, which the static flags leave out;
- LODs;
- a part limit for structures.

The timber and sci-fi kits use two or more materials, so they have no shared kit material. Their visual
consistency rests on the concepts and declared material regions.

## Status rule

- **Provisional** for "modular environment kits, `h100`/`final`, the fixed commit, Unity 6000.6.3f1 / URP 17.6.0" if
  all six runs pass.
- **Not Qualified** in any case: six runs cannot measure a failure rate.
