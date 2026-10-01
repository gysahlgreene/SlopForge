# Architecture

SlopForge is installed independently of Unity projects. Every invocation resolves a target project from `--project`, `SLOPFORGE_PROJECT_ROOT`, or by walking upward from the working directory for `ai/project.yaml`.

```text
CLI → project config + taxonomy + style pack → pipeline → backend
                                              ├─ image candidates → approval → Unity PNG
                                              ├─ concept candidates → approval → rembg → Hunyuan3D
                                              │  → Blender/PBR → preview Blend + Unity FBX
                                              └─ primitive → manifest route only
```

`slopforge/` owns project discovery, config, type/style validation, prompt assembly, candidate and manifest lifecycle, and validation. Pipelines call ComfyUI functions in `slopforge/backends/comfyui.py` and Blender functions in `slopforge/backends/blender.py`. These backends invoke utilities under `processing/` and Blender scripts under `blender/`. Workflows and project templates are data. These paths resolve relative to the package/tool installation, not the Unity project.

Workflow lookup checks, in order: the exact configured path under the project, `ai/workflows/<configured basename>`, then the bundled `workflows/<configured basename>`. This lets projects override a graph by name while keeping working defaults in the toolkit.

The manifest is JSON schema version 2 and is written atomically. It records semantic descriptions, style version, candidate history/selection, workflow and model metadata when exposed, inputs/outputs, validation measures, warnings, and status. Missing seed or model values remain null. Existing legacy manifests are upgraded while retaining unrecognized source fields under `legacy`.

Each new candidate also keeps its semantic description and style fingerprint. Approved image provenance comes from the selected candidate. Model approval rejects a changed active style before processing. These additive fields remain compatible with schema version 2; older candidates retain the metadata available when they were generated.

Candidate generation and 3D processing print flushed stage messages before starting expensive work. Image approval validates a temporary file and replaces the final PNG atomically. Project initialization preserves an existing manifest even with `--force`.

Conditioning is explicit. The shipped ComfyUI image workflow accepts text, so `text_only` is supported. Reference metadata can be selected for future backends, but reference mode currently fails clearly rather than claiming unsupported visual influence.
