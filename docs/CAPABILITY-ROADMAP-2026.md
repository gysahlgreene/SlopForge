# Capability and platform roadmap (2026-10)

This map separates reusable SlopForge systems from generated-content quality. “Implemented” means deterministic packaging or tested project behavior exists; it does not imply every model output is production-ready. See the [issue audit](AUDIT-2026-10.md), [workflow inventory](WORKFLOWS.md), and [upstream research verification](research/provider-source-verification-2026-10.md).

## Game-content lifecycle

| Area | Current state | Evidence and gap |
| --- | --- | --- |
| Visual development | **Partial** | Style packs, labeled exploration, explicit references and approval libraries exist. No art-bible/mood-board workflow; reference binding requires a configured graph, and the bundled image graph is text-only. |
| 2D icons/portraits | **Implemented, provider-dependent** | Candidate lifecycle, recipes, manifests and review work. The real H100 demo produced coherent potion icons, but transparency prompts yielded opaque RGB images. |
| Sprite sheets/animation | **Packaging implemented; generation unqualified** | Deterministic slicing, alpha metadata, atlas and timing exist. No verified workflow currently produces distinct, identity-consistent frames with usable alpha. Wan 2.2 trial was nearly static and opaque. |
| Tilemaps/tilesets | **Implemented with limits** | Deterministic tile slicing, edge diagnostics and Unity Tile assets exist. RuleTile/Tile Palette automation and proven arbitrary seam generation are absent. |
| 3D props/materials | **Experimental** | ComfyUI TRELLIS.2/Hunyuan paths, Blender processing, multi-view previews and Unity material export exist. Real output can have holes, disconnected geometry, UV/texture coverage defects; inspect before approval. |
| Modular environments | **Pack/checking implemented** | Recipes compose structures, props, materials and decals; Blender reports dimensions/origins/rotation and configured grid checks. No assembled demo room, terrain, foliage, roads or skybox pipeline. |
| 3D characters/creatures | **Partial / blocked on quality** | Character asset type and provider result contract exist. H100 character geometry failed topology gates; Rigify bounds fitting is humanoid-specific and does not repair surfaces. No qualified non-humanoid route. |
| Rigging/deformation | **Experimental** | Blender Rigify can run on synthetic watertight fixtures and emits pose evidence. Generated-character deformation failed review; pose displacement is not a quality score. |
| Animation/retargeting | **Partial** | Animation libraries, explicit bone maps, Blender retargeting and Unity Generic setup exist. Unity Humanoid import failed on required `RightHand`; representative retarget quality is not established. |
| UI packs | **Implemented** | Component/state recipes, no-baked-copy prompts, 9-slice metadata and optional Unity importer/prefab path exist. Full responsive HUD/menu generation remains follow-up. |
| VFX | **Packaging implemented; motion unqualified** | Deterministic sprite-sheet metadata and optional Unity ParticleSystem output exist. Actual transparent animated source sheets are workflow-dependent and not live-qualified. |
| Audio | **Not implemented; later** | Audio should use an audio-specific provider boundary, not be forced through ComfyUI. No chosen provider, rights review, or user-visible audio workflow justifies adding it before sprite/character quality is solved. |
| Unity delivery | **Partial** | PNG/FBX/material/tile/UI/VFX artifacts and optional editor-side generation exist. Unity owns `.meta`; Humanoid mapping is failed and a full Unity batch validation/fixture suite is not present. |
| QA/review | **Implemented foundations** | Static HTML review board, approval gates, image checks, mesh topology statistics, Blender measurements, pose evidence and optional Unity checks exist. Visual quality still requires a human; automated budgets/visual regression are incomplete. |

## Platform systems: NOW / SOON / LATER / NOT WORTH NOW

| System | Priority | Why |
| --- | --- | --- |
| Typed artifact relationships and recipe dependency graph | **NOW — implemented** | Required for packs and provenance; preserve this contract and fix regressions rather than adding another graph abstraction. |
| Quality tiers and local/remote backend separation | **NOW — implemented** | Profiles already separate from service location; keep host names out of product configuration defaults. |
| Workflow content hash and basic node/model-choice preflight | **NOW — implemented** | A workflow filename alone could silently identify changed content. New file-backed runs record SHA-256; doctor checks `/object_info` declarations. |
| Workflow requirement sidecars, pinned node identifiers and explainable missing dependencies | **NOW — #20** | A real mismatch gap remains: the API may expose a node class/model name without its package revision or weight identity. Record unknowns honestly; do not auto-install. |
| Reproducible generation manifest completeness | **SOON** | Add SlopForge version/commit, negative prompt, effective workflow overrides and portable model identifiers where reliably available. Avoid machine paths and do not claim to hash inaccessible server-side weights. |
| Representative deterministic asset QA | **SOON** | Prioritize alpha correctness, mesh components/manifoldness, texture coverage/UV validation, scale/pivot, Unity import and deformation acceptance because these are current user-facing failure modes. |
| Blender validation service/process boundary | **LATER** | Current local subprocess integration is sufficient for one developer machine; create a service only if throughput or isolation makes it necessary. |
| Unity batchmode validation | **SOON** | Useful for repeatable importer/controller checks and preventing regressions; keep Unity absent from normal CI and opt into it explicitly. |
| Model registry and weight checksum manager | **LATER** | Worth adding after upstream provenance/license fields are stable and weights can be identified without copying or downloading huge files. |
| Generation scheduler, VRAM resource classes, multiple workers | **LATER** | The H100 is a useful optional backend, but current user value is blocked by output quality rather than queue throughput. Add only after measured contention. |
| Artifact cache/deduplication | **LATER** | No demonstrated repeated-generation cost or storage bottleneck requires a cache yet; cache correctness would depend on complete provenance first. |
| Semantic asset search/tagging | **LATER** | Current local project/library sizes do not justify embeddings or a search service. Explicit categories and references cover current workflows. |
| Contact-sheet/turntable generation | **SOON** | Small deterministic evidence tools improve review and visual regression; reuse existing Pillow/Blender paths rather than adding a media framework. |
| Provider/plugin SDK | **NOT WORTH NOW** | There are few qualified providers and no demonstrated external extension ecosystem. Keep narrow provider boundaries such as rigging without designing a public SDK. |
| Audio generation system | **LATER** | Evaluate a provider and its commercial terms when prototype audio becomes an explicit user workflow; it should remain independent from image/video ComfyUI. |
| Full dependency-DAG scheduler, distributed worker fleet, billing/cost service | **NOT WORTH NOW** | Recipes already handle local dependencies; no team, scale, or measured cost data supports an orchestration platform. |

## ComfyUI workflow-family coverage

| Workflow family | State | Current boundary |
| --- | --- | --- |
| Text → concept/image | **Implemented and H100-tested** | Z-Image Turbo API graph; artifact and workflow hash recorded. Background transparency is not guaranteed. |
| Reference → image variation | **Partial** | Multiple references can be uploaded/bound through configured node mappings; no bundled reference graph or live visual-effect test. |
| Image → 3D mesh/PBR | **Experimental, H100 capability preflight passed** | TRELLIS.2 API graphs generate GLB/maps. 1024 path has prior successful runs; shape quality is not guaranteed. 1536 graph is prepared, not run in this audit. |
| Legacy image → Hunyuan3D mesh | **Implemented legacy route** | Inline graph in `processing/comfy_generate_3d.py`; not a checked-in API workflow file. Material treatment follows SlopForge's separate swatch path. |
| Mesh → surface swatch / mesh-aware PBR | **Implemented, quality-sensitive** | The path exists; report material preview evidence on actual mesh because neutral renders or saved map files alone do not establish coverage. |
| Background removal | **Implemented local deterministic/provider stage** | `rembg[cpu]` is a local dependency; exact downloaded weight license must be checked for distribution. No ComfyUI dependency is required. |
| Upscale/restoration | **Not a standard SlopForge generation capability** | Model files exist in the user's ComfyUI environment, but no current workflow/recipe coverage was confirmed in the product CLI. |
| Depth/normal/pose/edge/segmentation/inpaint/outpaint | **Planned capabilities** | No generic capability contract or bundled workflow family is established. Add workflows through requirement metadata/configuration, not new asset-type branches. |
| Character pose, turnaround, sprite animation, video → transparent frames | **Unqualified** | Current Wan test did not pass useful motion/alpha review. Deterministic frame processing cannot compensate for inadequate generated frames. |
| VFX sequence, material synthesis, UI concepts, environment concepts | **Partial/experimental** | Pack recipes/processors exist; generation quality and alpha/material constraints still depend on a compatible workflow. |
| Motion reference, audio | **Not implemented** | Evaluate separate providers where needed; these are not ComfyUI assumptions for the domain model. |

## Provider and licensing disposition

| Candidate | Disposition | Decision |
| --- | --- | --- |
| Z-Image Turbo Comfy-Org workflow | **Recommended for fast image generation** | Live H100 path works. Exact model-weight terms must be read from the selected upstream artifact; model files are not bundled. |
| TRELLIS.2 BF16 | **Recommended experimentally for props/environment on H100** | Upstream states Linux/NVIDIA, ≥24 GB, H100 testing and 512³–1536³. It expressly supports open/non-manifold surfaces, so do not use it as an animation-ready character promise. |
| Wan 2.2 | **Optional / experimental for motion** | Official code/model cards state Apache-2.0 and upstream documents ComfyUI integration; SlopForge’s chosen I2V sample was nearly static/opaque. H100 memory claims vary by model (A14B single-GPU recipe ≥80 GB; TI2V-5B can run on consumer hardware). |
| SkinTokens | **Optional / isolated evaluation** | Upstream calls it UniRig’s successor and states 14 GB VRAM/MIT. Training sources include ArticulationXL, VRoid Hub and ModelsResource; data splits/rights and SlopForge deformation quality remain unresolved. |
| UniRig | **Research baseline, not reliable fallback yet** | MIT labels exist, but current checkpoint coverage and full-stack requirements are incomplete/ambiguous. |
| ComfyUI-UniRig | **Avoid in production ComfyUI for now** | GPL-3 wrapper is not inherently non-commercial, but has experimental `comfy-env`/Pixi setup, bundled components and unpinned CUDA-sensitive dependencies. No installation was done. |
| Make-It-Animatable using Hunyuan3D 2.1 | **Research only for Ireland** | Hunyuan3D 2.1 license excludes EU/UK/South Korea; MIA code and weight terms are separate and do not remove that restriction. |
| OpenPose | **Avoid as a commercial default** | Official free-use terms are non-commercial; consider DWPose only after checking the exact checkpoint terms. |
| Larger Qwen-Image quality tier | **Not selected / needs current evaluation** | This audit did not establish an exact variant, current ComfyUI workflow, licensing, node set, and VRAM result; no weights were downloaded. |

More detailed sources and distinctions between code licenses, weight labels and training data are in [provider source verification](research/provider-source-verification-2026-10.md). These findings are not legal advice.

## ComfyUI service boundary and technical debt

`ComfyUIClient` currently covers `/system_stats`, `/object_info`, HTTP input upload, prompt submission, history polling, output enumeration, and `/view` output download. It validates graph node classes and selectable model choices and reports HTTP errors/timeouts. Live H100 tests exercised upload, byte-identical retrieval, queue/history, image output download, and recipe artifact creation. The API graph is sent directly; no SSH/SCP fallback is required for tested PNG/GLB file operations.

Known boundary limits:

- No streaming progress UI, queue-position reporting, cancellation API, or automatic retry. Avoid retrying prompt submission blindly because it can duplicate costly generations.
- `doctor` does not run a synthetic upload or inference; its checks are capability declarations, not end-to-end proof.
- The graph hash does not identify custom-node revisions or server-side model weight bytes.
- Prompt, seed, configured quality and reference provenance exist, but generated metadata does not fully capture SlopForge commit, negative prompt, server package versions, exact model hashes, all effective node inputs, or deterministic post-processing software versions.
- Unity `.meta` files remain editor-owned; Unity GUI/CLI validation is optional and not part of normal tests.
- Pillow tests emit three deprecation warnings for `Image.getdata()`; this is small maintenance debt, not a release blocker.

The H100 is an optional backend/profile opportunity for BF16, larger graphs and later batching. It is not a host-selection rule. Continue to configure backend URL and compute profile independently. Do not keep more models resident or add workers until measured use justifies the VRAM and operational tradeoff.
