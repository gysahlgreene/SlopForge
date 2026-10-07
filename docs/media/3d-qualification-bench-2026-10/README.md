# 3D qualification benchmark — October 2026

**2026-10-07 follow-up:** the retained 120-cell Basalt source now has a valid Unity Humanoid rig, evaluated diagnostic animation and user-approved body deformation. See [reviewed rig evidence](../character-qualification-2026-10/basalt-corrected-humanoid/README.md). Earlier failed generation attempts below remain historical failures; they were not promoted. Ashen remains unqualified at the configured mesh budget.

Offline re-inspection of the supplied review folders using Blender 5.1.0 and the current `blender/inspect_model.py`, with a 100,000-face budget. `summary.json` records input SHA-256, Blender runtime, mesh counts, topology, texture nodes, and report paths. The input files remain in `~/Downloads`; they were not modified.

## Ashen Cartographer

All tested reductions remain structurally unqualified at the 100k budget. The prepared mesh measures 245,224 faces and 1,201 components; the fixed-normal version 397,890 faces and 2,732 components; the fine version 692,041 faces and 8,799 components. The surface-preserving version retains 2,577,701 faces (about 20.5% of the raw report's 12,591,750), and the textured export has the same face count. The latter two both measure 58 components after GLB import. Existing four-view renders show the texture/shape detail, but also visible faceting and fragmented surface detail. These copies preserve useful high-frequency detail, but none meet this project's current mesh budget.

Blender inspection took about 1.5–11.1 seconds per file on this machine. This is local import and inspection time only; it excludes generation and reduction time.

## Basalt Warden

The supplied TripoSR GLB measures 58,792 faces, one component, one UV layer, and one image texture; structural inspection passes with a scale warning. It is a static source mesh, not a TRELLIS.2 result or a game-ready character.

The separate Blender-authored review candidate measures 40,880 faces, 93 components, seven material slots, and no image texture nodes. The character recipe's 64-component limit rejects it.

The concept-to-character benchmark ran through the remote ComfyUI endpoint at `http://<comfyui-host>:8188` on an NVIDIA H100 80 GB. The endpoint is reachable over the configured VPN; the earlier localhost refusal was only the Mac's local ComfyUI address. A standalone TRELLIS.2 run produced a 63,132-face mesh; the normal-tier 60,000-face preparation reduced it to 56,999 faces but introduced 549 boundary edges, so that candidate failed.

The real SlopForge path then used the normal tier's full two-attempt budget from the same reference. Attempt 1 generated and textured a mesh, but the reduced candidate had 1,470 components and 36,481 boundary edges. Attempt 2 generated a raw shape that Blender could not reduce to 60,000 faces; the retained raw mesh has 4,563,774 faces, no UV map, and 139,704 non-manifold edges. The asset manifest records both attempts and ends in `failed`, with no selected candidate or approval. Detailed prompt IDs, seeds, inference times, model names, source hashes, reports, and 4-view renders are retained in `h100_slopforge_run/` and `basalt_warden_h100.json`.

The standalone candidate's basecolor, roughness, and metallic maps are 2048²; its normal map is a 1×1 flat map. The live SlopForge candidate's four views show severe fragmented geometry. Visual approval, deformation review, and Unity import/playback remain pending. No Basalt result is game-ready.

### Voxel-remesh diagnostic

To isolate the 256-cell cleanup failure, the same Basalt 3D input and seed (`821096694`) were run through the production H100 TRELLIS.2 BF16 workflow with a 120-cell remesh. The final textured GLB imports at 43,480 faces, 4 components, zero boundary and non-manifold edges, zero degenerate faces, one UV layer, and four image textures. The maps, raw shape and prepared mesh remain outside Git. The workflow hash, prompt IDs, validation report, and four-view renders are in `h100_slopforge_run/ai/assets/candidates/character/basalt_warden_h100_retry/mesh_04/`.

This diagnostic is structurally qualified under the character limits, and its views are retained for human comparison. It was an extra benchmark run outside the recipe's two-candidate budget, so it was not inserted into the failed asset's manifest. The source was reviewed on 2026-10-07: orientation and starting pose were accepted, the overall shape read as one intended character with a tiny elbow stray, and visual quality was rejected as lumpy, low-resolution, and flat. It remains unapproved. The source is approximately 1 m tall; use Unity's 1 unit = 1 m convention and target approximately 1.8 m for an adult humanoid on the next candidate. Body deformation has separate user approval, and a Unity Humanoid diagnostic animation was evaluated; visible Unity playback and an acceptable visually reviewed source remain outstanding. The normal character recipe now configures the 120-cell cleanup while other asset types keep the existing 256-cell default; stochastic candidates still fail closed when they miss their structural limits.

The H100 inference service is a user systemd service whose manager exits when its last SSH session closes. That explained the apparent mid-run outages: keeping an SSH session open for the benchmark run let the queued inference and downloads complete. No persistent H100 login setting was changed.

## Limits

The runtime measurements cover ComfyUI inference only, not full cold-start or end-to-end turnaround. Structural reports and renders do not replace human visual approval, deformation review, Unity import, Humanoid mapping, or animation playback. The Ashen reductions exceed the configured mesh budget; the recipe-faithful Basalt result fails its boundary-edge check. Neither benchmark establishes production readiness.
