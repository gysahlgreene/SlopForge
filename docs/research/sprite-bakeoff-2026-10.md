# Sprite pipeline benchmark — 2026-10

## Result

The prompt-driven Wan 2.2 TI2V lane is **not a usable character-sprite provider** in this run. Idle, walk, and attack each produced 17 RGB frames at 768×768, but adjacent frames are nearly static, the requested actions are not clearly readable, and the model changes the goblin's face, proportions, and costume details across actions. No alpha, stable sprite bounds, pack, or Unity playback was produced. The later pose-transfer follow-up below is the strongest candidate, but remains exploratory and unvalidated in Unity.

This is a negative provider result, not a SlopForge quality pass. The runner and HTTP ComfyUI path worked. The model lane failed the visual conditions needed to proceed to engine validation.

## Test setup

- **Reference:** existing H100 input `slopforge/issue-9-qualification/slopforge-goblin-reference.png`, SHA-256 `08270b05b15e10fff9bd9189c96d413613e2f73dad227908754b7323aaec2e8f`. The repository contains no human-approval record for this image, so treat these outputs as exploratory evidence only.
- **Provider:** ComfyUI 0.37.0 on the remote H100, reached through the SlopForge HTTP client and a temporary SSH port forward. No graph or custom node was installed on the service.
- **Hardware:** NVIDIA H100 80 GB. Peak VRAM was not sampled during these runs.
- **Graph:** [wan22_ti2v_sprite_api.json](../media/sprite-bakeoff-2026-10/wan22_ti2v_sprite_api.json), SHA-256 `5febefa2cce4ed84c18cd3498d44ca96cb425392525efbf56b181f40ab0944dd`. It starts from the reference, requests a 17-frame 384×384 latent, and saves every decoded frame. ComfyUI emitted 768×768 RGB images.
- **Settings:** same graph, reference, seed `314159265`, negative prompt, 17 frames, 8 steps, square composition for all three actions. The exact positive prompt for each action is recorded below.
- **Models:** the three installed files match their SHA-256 LFS objects in `Comfy-Org/Wan_2.2_ComfyUI_Repackaged` at commit `ee6f4a40737a995bf5818954cfce6d59443b0f04`, repository license Apache-2.0:
  - `wan2.2_ti2v_5B_fp16.safetensors` — `456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e`
  - `umt5_xxl_fp8_e4m3fn_scaled.safetensors` — `c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68`
  - `wan2.2_vae.safetensors` — `e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156`
- **Matting:** not run in this TI2V bake-off. The installed `birefnet.safetensors` hash (`9ab37426bf4de0567af6b5d21b16151357149139362e6e8992021b8ce356a154`) does not match the separate HR-matting variant checked at the time, but it does match the official general `ZhengPeng7/BiRefNet` MIT artifact at commit `1c48c2d9c666dcb8faf8634ebb37d94b6071a4ba`. The standard BiRefNet model is the better provenance match for the installed file.
- **Reuse:** no external source code, model file, or workflow was copied into SlopForge. The API graph is a benchmark variant of the repository's existing Wan TI2V graph.

## Action prompts

All runs shared this negative prompt: `different character, changed costume, extra limbs, missing limbs, duplicated body, camera movement, zoom, cropped head, cropped feet, text, watermark, blur, flicker`.

| Action | Positive prompt | ComfyUI prompt ID | Inference time |
|---|---|---|---:|
| Idle | `The same full-body green goblin miner from the reference, with large copper goggles, teal backpack straps, dark brown overalls and a glowing amber lantern at his belt. Idle animation: subtle breathing, a small weight shift and one blink, feet planted, centered framing, fixed camera, keep the entire character and costume consistent.` | `3be3d495-d7de-4067-815a-019b99226e84` | 17.45 s (cold; no nodes cached) |
| Walk | `The same full-body green goblin miner from the reference, with large copper goggles, teal backpack straps, dark brown overalls and a glowing amber lantern at his belt. Walk animation: the character walks in place through a clear alternating left-right step cycle with counter-swinging arms, remains centered, fixed camera, keep the entire character and costume consistent.` | `5201c443-4d35-4e00-8a88-211bf8f6551c` | 3.27 s (warm; model/text nodes cached) |
| Attack | `The same full-body green goblin miner from the reference, with large copper goggles, teal backpack straps, dark brown overalls and a glowing amber lantern at his belt. Attack animation: perform one readable quick forward strike with the right arm, then recover to a ready stance; keep the full character centered, fixed camera, preserve the same identity and costume.` | `d2526fd8-aa72-4b38-8a9c-2f98344acafd` | 3.17 s (warm; model/text nodes cached) |

## Visual and structural review

This is an initial visual review for technical qualification, not human approval of a game asset. The reference itself also has no approval record in the repository.

| Action | Frames | Observed output | Decision |
|---|---|---|---|
| Idle | [Contact sheet](../media/sprite-bakeoff-2026-10/wan-ti2v-idle-contact.png) | Nearly static; the source's broad ears and large goggles become a different miner-like face and headwear. Background remains baked in. | Fail |
| Walk | [Contact sheet](../media/sprite-bakeoff-2026-10/wan-ti2v-walk-contact.png) | No convincing alternating leg cycle. The body becomes much thinner and taller, ears disappear, and the head/costume differs from both reference and other action rows. | Fail |
| Attack | [Contact sheet](../media/sprite-bakeoff-2026-10/wan-ti2v-attack-contact.png) | There is a small hand/arm gesture, but not a readable strike-and-recover cycle. Face, silhouette, and pose differ from the other rows; background remains baked in. | Fail |

All 51 output files are 768×768 RGB, so usable transparency is absent. A simple mean adjacent-frame RGB difference, after downsampling each frame to 160×160, was 0.222/255 for idle, 0.368/255 for walk, and 0.516/255 for attack. This diagnostic includes the mostly static background and is not a perceptual motion score; it agrees with the visual finding that the sequences have little movement.

The earlier Wan Animate result was promising but unqualified: it had real motion and alpha, but its frames touched the canvas edge and had no Unity playback. The live follow-up below captured an exact graph hash and corrected the clipping with additional input padding. The Wan Animate checkpoint, UMT5, CLIP Vision, and Wan VAE hashes match the licensed artifacts recorded in the workflow sidecar; BiRefNet matches the general MIT model. See the [workflow requirements](../../workflows/wan_animate_sprite_api.requirements.yaml), the [official model release](https://huggingface.co/Comfy-Org/Wan-Animate-2/tree/924563469bb8ac056e6171c3123a12903317606d), and the [prior candidate record](../media/candidates/wan-animate-goblin-candidate.json).

No TI2V frames were sent through the sprite packager or Unity. That output failed motion, identity, and alpha checks; the reference also has no approval record.

## Follow-up: live Wan Animate sprite lane

The prompt-only TI2V result was not usable, so the next run used the reference-and-pose-transfer graph at [wan_animate_sprite_api.json](../../workflows/wan_animate_sprite_api.json). The graph was authored against live ComfyUI core-node schemas; no external workflow JSON or source code was copied. Its input scale and centered padding are explicit workflow nodes, and both source files were uploaded through the existing SlopForge ComfyUI HTTP runner. The runner validated node classes and installed model choices before queueing inference.

- **Server:** ComfyUI 0.37.0 on NVIDIA H100 80 GB. Peak VRAM and exact execution duration were not captured. A later history query failed after the temporary tunnel stopped reaching the service; the successful prompt ID and output metadata are preserved locally.
- **Workflow:** SHA-256 `574c9f7add1c30f6a06e70f763b7b24eb59644c23dfe725e7d0b22f7a5928d75`.
- **Inputs:** goblin reference SHA-256 `08270b05b15e10fff9bd9189c96d413613e2f73dad227908754b7323aaec2e8f`; motion clip SHA-256 `77f96de1fb9004c19ddd9a92935717c156a6994258192e4b8a6aaea271b76946`.
- **Run:** seed `314159265`; prompt ID `4516c1bb-4b84-4b36-823d-f07063ad4177`; appearance prompt and runner output are in [wan-animate-dance-run.json](../media/sprite-bakeoff-2026-10/wan-animate-dance-run.json).
- **Motion source:** the supplied 17-frame clip is a dance, not an idle, walk, or attack driver. The prompt was corrected to describe the actual clip.
- **Processing:** character reference and driver frames are each scaled to 256×448 and padded to the 480×832 generation canvas. Wan Animate 2 transfers motion, then BiRefNet output is inverted and joined as alpha.
- **Output:** [17 raw RGBA frames](../media/sprite-bakeoff-2026-10/wan-animate-dance-frames/), [contact sheet](../media/sprite-bakeoff-2026-10/wan-animate-dance-contact.png), and [alpha bounds](../media/sprite-bakeoff-2026-10/wan-animate-dance-alpha-metrics.json).
- **Visual review:** identity, goggles, teal straps, overalls, lantern, and silhouette remained recognizable; the dance movement was readable. All 17 frames have alpha, and no foreground touches a frame edge. The nearest foreground edge is 92 px away. Character bounds vary from 148–285 px wide and 354–448 px tall; feet baselines vary by 31 px, so temporal alignment/root stability still needs review.
- **Decision:** this is the strongest live sprite-provider candidate so far, and the input padding removes the prior crop. It is an exploratory dance animation, not an approved sprite pack. The reference has no recorded human approval. No packer approval, Unity import, or Unity playback was run.

The preceding moderate-padding attempt still clipped foreground in frame 14. Its [exact graph](../media/sprite-bakeoff-2026-10/wan-animate-padded-api.json) (SHA-256 `5f17971bf8c68fed9c60da381f2af69f995e2cfd12e9b72cb6abd15e7a7a78e4`), [run manifest](../media/sprite-bakeoff-2026-10/wan-animate-padded-run.json), [contact sheet](../media/sprite-bakeoff-2026-10/wan-animate-padded-contact.png), and [alpha-bound report](../media/sprite-bakeoff-2026-10/wan-animate-padded-alpha-metrics.json) document why the graph was tightened further.

## Decision and follow-up

- Do not select the current prompt-driven TI2V path as the sprite provider.
- Keep the live Wan Animate graph as the leading candidate; benchmark action-specific motion sources, then validate alignment, a real sprite pack, Unity import, and playback before promoting it.
- Benchmark action-specific licensed motion drivers for idle, walk, and attack against a human-approved reference. Package and play only candidates that pass identity, motion, alpha, bounds, and anchor review.
- Do not promote a provider or close #9 from this result. #9 still needs Unity playback from a visually approved, transparent animation pack.

## Raw run artifacts

Each action folder contains all 17 emitted frames and the SlopForge runner metadata. [The complete manifest](../media/sprite-bakeoff-2026-10/manifest.json) records prompts, model/workflow hashes, run IDs, per-frame hashes, and settings. `wan-ti2v-metrics.json` contains the frame count, dimensions, color modes, and adjacent-frame differences. The raw outputs are experimental evidence and are not approved game assets.
