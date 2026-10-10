# Architecture

SlopForge is installed independently of Unity projects. Every invocation resolves a target project from `--project`, `SLOPFORGE_PROJECT_ROOT`, or by walking upward from the working directory for `ai/project.yaml`.

```text
CLI → project config + 3D taxonomy + style pack → recipe runner → asset pipeline → backend
                                                     ├─ concept/material inputs → review + provenance
                                                     ├─ image-to-3D model → Blender cleanup and previews
                                                     │  → material processing → Unity FBX and maps
                                                     ├─ character mesh → readiness → rigging
                                                     │  → deformation review → animation/Unity
```

`slopforge/` owns project discovery, config, type/style validation, prompt assembly, candidate and manifest lifecycle, and validation. `ComfyUIClient` in `slopforge/backends/comfyui.py` is the single inference-service boundary for HTTP health/node discovery, uploads, prompt submission, history, output discovery, and downloads. The local and remote backends use identical HTTP operations; all Blender processing stays on the SlopForge machine. `COMFYUI_URL` chooses the service location, while `SLOPFORGE_COMPUTE_PROFILE` chooses the workflows/models independently. `COMFYUI_HOME` is no longer required for file transfer. Blender functions remain in `slopforge/backends/blender.py`; helper scripts live under `processing/` and Blender scripts under `blender/`. Workflows and project templates are data and project workflow overrides take precedence over bundled files.

Workflow lookup checks, in order: the exact configured path under the project, `ai/workflows/<configured basename>`, then the bundled `workflows/<configured basename>`. This lets projects override a graph by name while keeping working defaults in the toolkit.

Recipes under `ai/recipes/` compose registered atomic pipeline handlers. Instances and child assets share the manifest, with parent/dependency IDs, persisted stage state, per-child provenance, and typed aggregate outputs. See [Recipe and pack orchestration](RECIPES.md).

The manifest is JSON schema version 4 and is written atomically. Existing asset fields and the path-only `outputs` map remain compatible. Prop records also have `executions`, each with a unique invocation ID, parent execution link when known, semantic `identity_inputs` and SHA-256, terminal execution status, and ordered stage attempts. Stages persist `pending`, `running`, `succeeded`, or `failed`, with settings, provenance, errors, and typed artifact references. References carry project-relative locations for finding files, content hashes for identity, and IDs/hashes for upstream artifacts; path names do not define artifact identity.

Schema v3 manifests migrate to v4 with `executions: []` and explicit `lineage_status: {status: "unknown", reason: "legacy manifest predates execution lineage"}`. Migration preserves existing claims and fields and does not synthesize runs, stage outcomes, artifact hashes, or stronger provenance. See [Typed asset outputs](ASSET-OUTPUTS.md) for the prop record shape and compatibility views.

Prop execution identity hashes canonical semantic inputs: brief, selected concept content hash, resolved workflow identity, configured workflow inputs, effective generation/processing settings, and generation seeds. Generated outputs, UUIDs, timestamps, prompt IDs, attempt numbers, temporary upload names, filesystem paths, and destination filenames are not identity inputs. Sidecars separately record source and effective graph hashes, effective bindings, output content hashes, and known runtime facts. Inference outputs do not retroactively define their producing execution identity.

The prop stage journal uses the existing synchronous pipeline boundaries: `concept_generation`, `conditioning_preparation`, `mesh_workflow_execution`, `mesh_raw_acquisition` where a workflow returns a separate raw mesh, `mesh_preparation` where applicable, `material_generation`, `mesh_output_acquisition`, `material_map_acquisition` for swatch-derived maps, `material_assembly_export`, and `final_publication`. ComfyUI's internal shape, Blender preparation, material, and download boundaries are journaled in the worker through the same manifest and atomic save/load path. The 3D worker saves each fully bound workflow identity and binding set to stage provenance before queueing. Image generation sidecars record source/effective graph identity and bindings after successful output acquisition. Generated-output bindings remain stage evidence and do not change the execution's semantic identity. This records evidence only; it makes no reuse, invalidation, or automatic resume decision.

Provenance facts distinguish `known` with a value, `unavailable` after the relevant backend boundary did not expose the fact, and `not_recorded` when the integration did not collect it. ComfyUI health may expose provider version and device names. Exact model weights and custom-node revisions remain `unavailable` unless the service exposes trustworthy revisions; configured model filenames are recorded as filenames and do not establish weight identity. The synthesized Hunyuan3D workflow has no source file hash, so its source-file provenance is explicitly unavailable while its effective graph identity is recorded.

Each new candidate also keeps its semantic description and style fingerprint. Approved image provenance comes from the selected candidate. Model approval rejects a changed active style before processing. Additive fields preserve existing candidate and output metadata during schema migration; older candidates retain the metadata available when they were generated.

Candidate generation and 3D processing print flushed stage messages before starting expensive work. Image approval validates a temporary file and replaces the final PNG atomically. Project initialization preserves an existing manifest even with `--force`.

Conditioning is explicit. `text_only` keeps the bundled concept graph unchanged. Reference mode uploads selected approved images and binds them through project-configured workflow inputs; graphs without mappings fail before queueing. Images support concept and material stages for 3D assets. Reference storage stays independent of ComfyUI node types.
