# Sprite pipeline benchmark — 2026-10

## Result

The prompt-driven Wan 2.2 TI2V lane is **not a usable character-sprite provider** in this run. Idle, walk, and attack each produced 17 RGB frames at 768×768, but adjacent frames are nearly static, the requested actions are not clearly readable, and the model changes the goblin's face, proportions, and costume details across actions. No alpha, stable sprite bounds, pack, or Unity playback was produced. The later pose-transfer follow-up was also rejected by the user and is not a leading candidate.

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

The earlier Wan Animate follow-up produced real motion and alpha and corrected edge clipping with input padding, but the resulting sprite was rejected by the user as visually unacceptable. This is a failed comparison, not the strongest candidate. The Wan Animate checkpoint, UMT5, CLIP Vision, and Wan VAE hashes match the licensed artifacts recorded in the workflow sidecar; BiRefNet matches the general MIT model. The product workflow and its sidecar were retired with the 3D-only scope; the tested graph remains in [benchmark evidence](../media/sprite-bakeoff-2026-10/wan-animate-padded-api.json). See the [official model release](https://huggingface.co/Comfy-Org/Wan-Animate-2/tree/924563469bb8ac056e6171c3123a12903317606d) and [prior candidate record](../media/candidates/wan-animate-goblin-candidate.json).

No TI2V frames were sent through the sprite packager or Unity. That output failed motion, identity, and alpha checks; the reference also has no approval record. The pose-transfer output was not accepted as a product-quality result and has not been packaged or tested in Unity either.

## Required next comparison

Do not keep refining either SlopForge-authored Wan graph as the default path. The adapted W2 run and external loop gate below show that this local Wan route does not currently produce a usable walk cycle. The next generation comparison should use the existing provider-backed video lane in `sprite-gen`; it calls Grok Imagine through a paid xAI API, so no request was made without explicit cost authorization. Keep generation quality and deterministic frame processing scored separately.

## External pipeline source/output audit

The staged workflow was cloned for inspection at commit `9fee239216b8fb5a841401644a4ef629496e563c`. The three graphs are real API-format workflows, with small Python drivers that submit to ComfyUI, poll execution history and connect the MP4 result to the sheet stage. W1 takes an editable COCO-18 pose map; W2 starts from that one posed keyframe and lets Wan 2.2 invent later frames; W3 uses BiRefNet, scales to 128px cells and stitches a strip. W3 converts to grayscale for runtime tinting, which is a product mismatch for SlopForge's current full-color pack contract.

I inspected the committed upstream examples as well as their documentation. The idle sheet is a very low-detail gray outline character with little visible motion; the walk sample shows a more readable alternating gait, and the in-air sample changes silhouette clearly. These establish that the extraction/assembly path can produce a regular cell strip and that some actions are animated. They do not show SlopForge's goblin identity, color style, action specificity, Unity playback, or broad character consistency, so they do not qualify the provider.

The active H100 ComfyUI is version 0.37.0 and has Wan 2.2 FP8 models/Lightx2v LoRAs available, but its `/object_info` lacks the upstream custom nodes `UnetLoaderGGUF`, `CLIPLoaderGGUF`, `VRAMUnloadClip`, `VRAMUnloadModel`, and `BiRefNetRMBG`. The Qwen edit/ControlNet weights are also absent. Do not install those nodes into the active service. The upstream W2 GGUF model repository currently has no declared license metadata, so do not download/use those converted weights. A compliant benchmark needs a disposable ComfyUI copy, verified W1 weights, and an adapted W2 graph using the already installed official Wan weights if their exact source hashes and LoRA license are confirmed.

The deterministic sprite package was initially cloned at release `v2.20.0`, commit `d993e5300b4255111e8ee0e29779caea1b3b97bd`. Current `v2.35.0` was then verified at commit `47e985b6320eb000e587632c2cd62a98b1bc5c99` (Apache-2.0); the older checkout was advanced only inside its disposable `/tmp` clone for benchmark execution. Its current source contains detailed video canvas, alpha extraction, periodic-cycle detection, alignment, curation and engine export stages. Its example sprites are visually clearer than the committed staged workflow samples, but no provider-backed generation request was made because that path calls paid hosted APIs.

## Follow-up: live Wan Animate sprite lane

The prompt-only TI2V result was not usable, so the next run used the reference-and-pose-transfer graph preserved as [wan-animate-padded-api.json](../media/sprite-bakeoff-2026-10/wan-animate-padded-api.json). The graph was authored against live ComfyUI core-node schemas; no external workflow JSON or source code was copied. Its input scale and centered padding are explicit workflow nodes, and both source files were uploaded through the existing SlopForge ComfyUI HTTP runner. The runner validated node classes and installed model choices before queueing inference.

- **Server:** ComfyUI 0.37.0 on NVIDIA H100 80 GB. Peak VRAM and exact execution duration were not captured. A later history query failed after the temporary tunnel stopped reaching the service; the successful prompt ID and output metadata are preserved locally.
- **Workflow:** SHA-256 `574c9f7add1c30f6a06e70f763b7b24eb59644c23dfe725e7d0b22f7a5928d75`.
- **Inputs:** goblin reference SHA-256 `08270b05b15e10fff9bd9189c96d413613e2f73dad227908754b7323aaec2e8f`; motion clip SHA-256 `77f96de1fb9004c19ddd9a92935717c156a6994258192e4b8a6aaea271b76946`.
- **Run:** seed `314159265`; prompt ID `4516c1bb-4b84-4b36-823d-f07063ad4177`; appearance prompt and runner output are in [wan-animate-dance-run.json](../media/sprite-bakeoff-2026-10/wan-animate-dance-run.json).
- **Motion source:** the supplied 17-frame clip is a dance, not an idle, walk, or attack driver. The prompt was corrected to describe the actual clip.
- **Processing:** character reference and driver frames are each scaled to 256×448 and padded to the 480×832 generation canvas. Wan Animate 2 transfers motion, then BiRefNet output is inverted and joined as alpha.
- **Output:** [17 raw RGBA frames](../media/sprite-bakeoff-2026-10/wan-animate-dance-frames), [contact sheet](../media/sprite-bakeoff-2026-10/wan-animate-dance-contact.png), and [alpha bounds](../media/sprite-bakeoff-2026-10/wan-animate-dance-alpha-metrics.json).
- **Visual review:** identity, goggles, teal straps, overalls, lantern, and silhouette remained recognizable; the dance movement was readable. All 17 frames have alpha, and no foreground touches a frame edge. The nearest foreground edge is 92 px away. Character bounds vary from 148–285 px wide and 354–448 px tall; feet baselines vary by 31 px.
- **Decision:** the user rejected this result. It is not a selected provider or an approved sprite pack. No packer approval, Unity import, or Unity playback was run.

The preceding moderate-padding attempt still clipped foreground in frame 14. Its [exact graph](../media/sprite-bakeoff-2026-10/wan-animate-padded-api.json) (SHA-256 `5f17971bf8c68fed9c60da381f2af69f995e2cfd12e9b72cb6abd15e7a7a78e4`), [run manifest](../media/sprite-bakeoff-2026-10/wan-animate-padded-run.json), [contact sheet](../media/sprite-bakeoff-2026-10/wan-animate-padded-contact.png), and [alpha-bound report](../media/sprite-bakeoff-2026-10/wan-animate-padded-alpha-metrics.json) document why the graph was tightened further.

## Decision and follow-up

- Do not select the current prompt-driven TI2V path as the sprite provider.
- Retire the current Wan Animate and TI2V results as provider candidates; retain their graphs only as negative benchmark evidence.
- Prioritize a benchmark through the mature provider-backed sprite pipeline after cost authorization; its video generation uses a paid hosted API.
- Keep transparency extraction and automatic cycle/seam rejection as reusable processing stages. Require common bounds, baseline review, and a real pack before Unity import and playback.
- Do not promote a provider or close #9 from this result. #9 still needs Unity playback from a visually approved, transparent animation pack.

## Raw run artifacts

Each action folder contains all 17 emitted frames and the SlopForge runner metadata. [The complete manifest](../media/sprite-bakeoff-2026-10/manifest.json) records prompts, model/workflow hashes, run IDs, per-frame hashes, and settings. `wan-ti2v-metrics.json` contains the frame count, dimensions, color modes, and adjacent-frame differences. The raw outputs are experimental evidence and are not approved game assets.

## Follow-up: adapted staged W2 and external cycle QA — 2026-10-06

The staged workflow's W1 pose-edit stage could not run on the active H100 because its Qwen/ControlNet weights and required custom nodes were absent. I did not install them into the shared ComfyUI service or use its unlicensed GGUF conversion. Instead I adapted the W2 API graph to the already-installed official Wan 2.2 14B FP8 checkpoints and official Lightx2v LoRAs, supplied the existing goblin reference, then used ComfyUI core plus the installed MIT BiRefNet checkpoint for alpha extraction. The W2 result is still a Wan video-generation result, so this is a controlled test of the staged graph's W2 and deterministic QA—not evidence that the full W1→W2→W3 route has been qualified.

- **Inference:** seed `314159265`; 33 frames at 512×512 and 16 fps; 38.71 seconds on the H100. Prompt ID `02baf33c-4458-4114-b1ed-a09099288c88`. [Video](../media/sprite-bakeoff-2026-10/external-w2-walk/walk.mp4), [all-frame contact sheet](../media/sprite-bakeoff-2026-10/external-w2-walk/walk-contact.png), and [adapted W2 graph](../media/sprite-bakeoff-2026-10/external-w2-walk/w2-api.json).
- **Visual result:** goblin identity and costume remain recognizable, better than the prior prompt-only TI2V run. The first part is nearly static and the step arrives late; the 2.06-second clip does not contain a repeating gait. It is not a qualified walk animation.
- **Matting:** the H100's official general BiRefNet checkpoint (MIT, SHA-256 `9ab37426bf4de0567af6b5d21b16151357149139362e6e8992021b8ce356a154`) produced 33 transparent RGBA frames using core ComfyUI nodes. [Transparent contact sheet](../media/sprite-bakeoff-2026-10/external-w2-walk/walk-alpha-contact.png), [bounds report](../media/sprite-bakeoff-2026-10/external-w2-walk/alpha-bounds.json), and [matting graph](../media/sprite-bakeoff-2026-10/external-w2-walk/matting-api.json). Bounds vary from 245–316 px wide and 402–456 px tall; feet baselines vary from 476–494 px. The mask required inversion before joining as alpha.
- **External QA:** `sprite-gen` v2.35.0, commit `47e985b6320eb000e587632c2cd62a98b1bc5c99`, license Apache-2.0. Its real `video-loop --state walk --fps 16 --cycle auto` implementation rejected the frames: periodicity `-0.07 < 0.150` over the walk window `[8,16]`. No loop strip or sprite pack was emitted. This is useful evidence that a cycle/seam gate catches a plausible-looking but non-looping clip before packaging.
- **Reuse decision:** keep the current SlopForge Wan generations rejected. Adapt the upstream periodicity/seam gate and deterministic frame processing behind SlopForge's provider contract; do not copy upstream code until the version-pinned component and dependency/license review is complete. The actual source checkout, output files, both graphs and run details are preserved in the linked evidence folder; [run manifest](../media/sprite-bakeoff-2026-10/external-w2-walk/run-manifest.json).
- **Next provider comparison:** the current upstream generation path calls Grok Imagine through xAI's paid API. It was inspected but not invoked. The next benchmark is gated on explicit budget/account authorization; no hosted provider was billed in this run.
