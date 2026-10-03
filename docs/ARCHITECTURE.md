# Architecture

SlopForge is installed independently of Unity projects. Every invocation resolves a target project from `--project`, `SLOPFORGE_PROJECT_ROOT`, or by walking upward from the working directory for `ai/project.yaml`.

```text
CLI → project config + taxonomy + style pack → pipeline → backend
                                              ├─ image candidates → approval → Unity PNG
                                              ├─ concept candidates → approval → rembg → Hunyuan3D
                                              │  → Blender/PBR → preview Blend + Unity FBX
                                              └─ primitive → manifest route only
```

`slopforge/` owns project discovery, config, type/style validation, prompt assembly, candidate and manifest lifecycle, and validation. `ComfyUIClient` in `slopforge/backends/comfyui.py` is the single inference-service boundary for HTTP health/node discovery, uploads, prompt submission, history, output discovery, and downloads. The local and remote backends use identical HTTP operations; all Blender processing stays on the SlopForge machine. `COMFYUI_URL` chooses the service location, while `SLOPFORGE_COMPUTE_PROFILE` chooses the workflows/models independently. `COMFYUI_HOME` is no longer required for file transfer. Blender functions remain in `slopforge/backends/blender.py`; helper scripts live under `processing/` and Blender scripts under `blender/`. Workflows and project templates are data and project workflow overrides take precedence over bundled files.

Workflow lookup checks, in order: the exact configured path under the project, `ai/workflows/<configured basename>`, then the bundled `workflows/<configured basename>`. This lets projects override a graph by name while keeping working defaults in the toolkit.

The manifest is JSON schema version 2 and is written atomically. It records semantic descriptions, style version, candidate history/selection, workflow and model metadata when exposed, inputs/outputs, validation measures, warnings, and status. Missing seed or model values remain null. Existing legacy manifests are upgraded while retaining unrecognized source fields under `legacy`.

Each new candidate also keeps its semantic description and style fingerprint. Approved image provenance comes from the selected candidate. Model approval rejects a changed active style before processing. These additive fields remain compatible with schema version 2; older candidates retain the metadata available when they were generated.

Candidate generation and 3D processing print flushed stage messages before starting expensive work. Image approval validates a temporary file and replaces the final PNG atomically. Project initialization preserves an existing manifest even with `--force`.

Conditioning is explicit. The shipped ComfyUI image workflow accepts text, so `text_only` is supported. Reference metadata can be selected for future backends, but reference mode currently fails clearly rather than claiming unsupported visual influence.
