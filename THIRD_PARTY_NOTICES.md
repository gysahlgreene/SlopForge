# Third-party notices

SlopForge is licensed under MIT; see `LICENSE`. No ComfyUI implementation source, custom node code, or model weights are bundled. Included examples and public benchmark evidence are limited to the assets documented in this repository.

The image workflow is a local ComfyUI API-format graph using ComfyUI core node names. Its source-machine provenance and the model references are documented in `LICENSE-PROVENANCE.md` and `docs/COMFYUI.md`. The Hunyuan3D API graph is assembled by SlopForge from node names exposed by the local ComfyUI installation.

Python dependencies are installed from their upstream packages and remain under their respective licenses. Model weights and ComfyUI custom nodes installed separately are not covered by SlopForge's license; review their publishers' terms before use or redistribution.

Concept images use Z-Image Turbo (Apache-2.0) with the Qwen3 4B text encoder (Apache-2.0) and FLUX.1 [schnell]'s autoencoder (`ae.safetensors`, byte-identical to Black Forest Labs' Apache-2.0 release). The tiling-material upscaler file `RealESRGAN_x4plus.safetensors` is [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)'s release `RealESRGAN_x4plus.pth` (BSD-3-Clause, v0.1.0, sha256 `4fa0d389`) converted by `scripts/convert-realesrgan.py` (sha256 `37f9a931`); its source and both hashes are in the workflow's sidecar. Every bundled workflow sidecar records each model's output rights, read on 2026-10-27 (docs/COMFYUI.md, Providers and output rights).

Concept and view cut-outs remove the background with [rembg](https://github.com/danielgatis/rembg) (MIT), naming [BiRefNet](https://github.com/ZhengPeng7/BiRefNet)'s general model (MIT) in `processing/background.py`; its weights (about 1 GB) download from their publisher on first use. Until 2026-10-26 the cut-outs used rembg's default model, BRIA [RMBG-2.0](https://huggingface.co/briaai/RMBG-2.0), which is licensed CC BY-NC 4.0 (non-commercial use only); the conditioning stage records the background tool's hash, so cut-outs made with it are not reused.

Creature motion clips use [Wan 2.2](https://huggingface.co/Wan-AI/Wan2.2-I2V-A14B) image-to-video (Apache-2.0) with Google's umT5-XXL text encoder (Apache-2.0) and the Wan 2.1 VAE (Apache-2.0), from Comfy-Org's repackaging; the workflow sidecar records each file's SHA-256 and output rights, read on 2026-10-28. No weights are bundled.

TRELLIS.2 graphs condition on Meta's [DINOv3](https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m) ViT-L, licensed under the DINOv3 License: royalty-free, including commercial use, with conditions that include displaying "Built with DINOv3" and excluding end uses prohibited by trade controls, such as military ones. Built with DINOv3. The licence's section 1.b.v excludes end uses related to weapons where trade controls apply; the project owner's reading (2026-10-27, a reading, not legal advice) is that it concerns trade-controlled uses such as real weapons, defence and export-controlled work, not game art of fictional weapons.

The optional `slopforge character rig` command invokes Blender's bundled Rigify add-on through the installed Blender executable. The provider records GPL-2.0-or-later provenance and Blender version in the character manifest. Blender/Rigify is not bundled by SlopForge; consult the installed Blender distribution's license notices. No UniRig/SkinTokens code or weights are bundled or installed.

Declared weapon parts (`--part`) are masked by `processing/part_masks.py`, which loads two models in a separately installed environment (`scripts/install-part-masks.sh`): [Florence-2 large](https://huggingface.co/florence-community/Florence-2-large) (MIT) and [SAM 2.1 Hiera large](https://huggingface.co/facebook/sam2.1-hiera-large) (Apache-2.0), through Hugging Face `transformers` (Apache-2.0) and PyTorch (BSD-3-Clause). No weights are bundled; they download from their publishers.

A weapon that declares a moving part is generated as separate parts by `processing/part_model.py`, which runs [OmniPart](https://github.com/HKU-MMLab/OmniPart) (MIT, revision `ceb1a4ff`; its weights `omnipart/OmniPart` are MIT, revision `dfc4b4c7`) in a separately installed environment (`scripts/install-omnipart.sh`), built on [TRELLIS](https://github.com/microsoft/TRELLIS) (MIT). OmniPart's layout stage depends on NVIDIA PartField, which is licensed for non-commercial use only: SlopForge never calls it and does not download its checkpoint; the 3D part boxes come from the parts' own masks. Its part synthesis, which SlopForge does run, decodes meshes with NVIDIA FlexiCubes and writes GLBs with nvdiffrast, both under the NVIDIA Source Code License: "only may be used or intended for use non-commercially" (section 3.3; read 2026-10-27 at OmniPart `ceb1a4ff`). SlopForge therefore records the outputs of the OmniPart and hybrid part routes as `restricted` and refuses to deliver them. No weights are bundled; they download from their publishers.

Creature motion from video uses [video2rig](https://github.com/canitcode/video2rig) (AGPL-3.0, commit `55d51b3`), installed separately with its own environment by `scripts/install-video2rig.sh` and run by `slopforge/backends/video2rig.py` through its command line only: SlopForge never bundles or modifies it and no SlopForge module imports it (the install and preflight checks only ask the tool's own Python to load it), so its licence does not extend to SlopForge's MIT code. Running it asks nothing beyond keeping its licence and notices. Anyone who modifies it, or offers SlopForge as a service that runs it for others over a network, must offer those users the complete corresponding source of the video2rig they run, including any modification, under AGPL-3.0 (its section 13); SlopForge therefore runs an unmodified checkout at a pinned commit, and a needed fix goes upstream. Its joint reader is built on [DINOv2-small](https://huggingface.co/facebook/dinov2-small) (Apache-2.0), which the install script downloads at revision `ed25f3a3` and the tool reads offline. video2rig vendors BootsTAPIR (Apache-2.0) for an older tracking road that SlopForge does not use. Output rights: cleared. The AGPL covers the program, not its outputs, and the author's README states that the animations made with it are the user's, "commercial games included" (read 2026-10-27 at commit `55d51b3`); a clip's rights also depend on the video it was read from. No weights are bundled.

The local Cesium Man rigging benchmark fixture comes from the Khronos [glTF Sample Assets](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/CesiumMan). The model and its metadata are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode); Cesium logos and trademarks have separate restrictions listed in the upstream [legal marks notice](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/main/LICENSES/LicenseRef-LegalMark-Cesium.txt). SlopForge’s MIT license does not replace those terms.

## Models and tools

No model weights are bundled; each is downloaded from its publisher. The default `h100` profiles use:

| Stage | Model or tool | Licence |
| --- | --- | --- |
| Concept images | [Z-Image Turbo](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo) with the [Qwen3 4B](https://huggingface.co/Qwen/Qwen3-4B) text encoder and [FLUX.1 [schnell]](https://huggingface.co/black-forest-labs/FLUX.1-schnell)'s autoencoder ([ComfyUI files](https://huggingface.co/Comfy-Org/z_image_turbo)) | Apache-2.0 |
| Character poses, shape guides | [Z-Image-Turbo Fun ControlNet Union 2.1](https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1) | Apache-2.0 |
| Background removal | [BiRefNet](https://github.com/ZhengPeng7/BiRefNet) general, through [rembg](https://github.com/danielgatis/rembg) | MIT |
| Image to 3D mesh and PBR maps | [TRELLIS.2](https://huggingface.co/microsoft/TRELLIS.2-4B) ([ComfyUI files](https://huggingface.co/Comfy-Org/TRELLIS.2)), conditioned by [DINOv3 ViT-L](https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m) | MIT; DINOv3 License |
| Multi-view 3D (experimental) | [Pixal3D](https://huggingface.co/Comfy-Org/Pixal3D) by TencentARC, conditioned by DINOv3 with the NAF upsampler; views by [Qwen-Image-Edit-2511](https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI) with [Qwen2.5-VL 7B](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI) and the [multiple-angles LoRA](https://huggingface.co/fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA) | MIT; DINOv3 License; Apache-2.0 |
| Open pictures of a chest, characters' head and body pictures (experimental) | [Qwen-Image-Edit-2511](https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI) with [Qwen2.5-VL 7B](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI) | Apache-2.0 |
| Part masks | [Florence-2 large](https://huggingface.co/florence-community/Florence-2-large) and [SAM 2.1 Hiera large](https://huggingface.co/facebook/sam2.1-hiera-large) | MIT; Apache-2.0 |
| Part layout for moving parts | [OmniPart](https://github.com/HKU-MMLab/OmniPart), built on [TRELLIS](https://github.com/microsoft/TRELLIS) | MIT; its NVIDIA FlexiCubes and nvdiffrast are non-commercial, so delivery refuses what it makes |
| Tiling material upscale | [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) x4plus | BSD-3-Clause |
| Character rigging | [SkinTokens](https://github.com/VAST-AI-Research/SkinTokens), or Blender's Rigify | MIT; GPL-2.0+ |
| Character motion | [CMU Graphics Lab Motion Capture Database](http://mocap.cs.cmu.edu/) | Free for any use, not resold |
| Character clips in Unity | [Quaternius Universal Animation Library](https://quaternius.com/packs/universalanimationlibrary.html), downloaded separately | CC0 |
| Creature motion from video | [Wan 2.2](https://huggingface.co/Wan-AI/Wan2.2-I2V-A14B) image-to-video, read onto the rig by [video2rig](https://github.com/canitcode/video2rig), run as a separate program | Apache-2.0; AGPL-3.0 |
| Inference server | [ComfyUI](https://github.com/comfyanonymous/ComfyUI), on your machine or a remote GPU | GPL-3.0 |
| Mesh processing, UVs, normal bakes, review renders | [Blender](https://www.blender.org/) 5.1 | GPL-2.0+ |
| Engine delivery, prefabs, Play-mode checks | [Unity](https://unity.com/) 6000.6.3f1, URP 17.6.0, Unity Test Framework | Unity's terms |

**Built with DINOv3.** Its licence allows commercial use, but it is Meta's own licence, not MIT or Apache: it
requires this attribution and excludes military uses. Until 2026-10-26 the cut-outs used rembg's default model, BRIA
RMBG-2.0, which is licensed for non-commercial use only. They now use BiRefNet, with near-identical cut-outs (alpha
IoU 0.995–0.998). The legacy Hunyuan3D 2.0 route, used only when no model workflow is configured, is under Tencent's
community licence; nothing shown here used it. Full model files, hashes and graphs:
[workflow inventory](docs/WORKFLOWS.md) · [ComfyUI setup](docs/COMFYUI.md)
