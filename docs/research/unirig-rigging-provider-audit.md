# Automatic rigging provider audit: UniRig and SkinTokens

**Checked:** 2026-10-04. Sources below are first-party repositories/model cards, the authors’ papers, or platform documentation. This is a compatibility and license inventory, not an inference test or legal opinion.

## Finding

Use **SkinTokens / TokenRig** as the first candidate for issue #14’s optional automatic-rigging provider; do not start a new integration against UniRig alone. The UniRig maintainers identify SkinTokens as its successor. SkinTokens combines skeleton and skin-weight prediction, publishes inference code and checkpoints, and documents an NVIDIA GPU requirement of 14 GB. UniRig remains a useful reference/fallback because it has an MIT codebase and explicit staged skeleton/skin/merge commands, but its current README says checkpoint releases are progressive and its model card is internally inconsistent about which components/checkpoints are actually available.

This is a candidate, not an approved production provider: neither project establishes reliable deformation for arbitrary SlopForge-generated characters, and dataset/model training-data commercial rights are not fully documented in the reviewed sources. Rig review and explicit user approval must remain in the pipeline.

## UniRig

| Area | Verified from upstream |
|---|---|
| Source and status | [Official VAST-AI-Research/UniRig repository](https://github.com/VAST-AI-Research/UniRig/tree/6793c6640ff01c8fb389f3993434124bb43d2933), pinned to the reviewed `main` commit. README describes the SIGGRAPH 2025 system as two stages: skeleton prediction, then skin-weight/attribute prediction. It names [SkinTokens](https://github.com/VAST-AI-Research/SkinTokens) as its successor. |
| Software/model license | Repository [LICENSE](https://github.com/VAST-AI-Research/UniRig/blob/6793c6640ff01c8fb389f3993434124bb43d2933/LICENSE) is MIT. The [UniRig Hugging Face model card](https://huggingface.co/VAST-AI/UniRig) declares `license: mit`. That declaration does not establish rights for all training data or derivative source assets. |
| Hardware / platform | README requires Python 3.11 and PyTorch >=2.3.1, plus CUDA-oriented `spconv`, `torch_scatter`, `torch_cluster`, and `flash_attn`; it gives no supported-OS matrix or minimum inference VRAM. Therefore Linux/CUDA is a plausible target, not an officially stated support guarantee. |
| Inputs and outputs | README lists `.obj`, `.fbx`, `.glb`, `.vrm` skeleton inputs; skinning consumes the skeleton-stage FBX; merge combines the prediction with the original and writes `.glb` in its example. The stages are shell scripts (`launch/inference/generate_skeleton.sh`, `generate_skin.sh`, `merge.sh`). |
| Blender / Unity | It documents an optional modified VRM Blender add-on and dataset-to-FBX export. No Unity integration or Unity validation is documented. Since its merge example outputs GLB, Unity use needs an explicit glTF import path or a tested Blender-to-FBX conversion. |
| Quality caveat | README explicitly warns skinning may degrade significantly when the predicted skeleton is inaccurate (examples: missing tail/wing bones) and recommends refining the skeleton first. This directly argues against automatic approval. |

### UniRig release ambiguity

The [repository README](https://github.com/VAST-AI-Research/UniRig/tree/6793c6640ff01c8fb389f3993434124bb43d2933#current-release-status--roadmap) says skeleton and skinning prediction code/checkpoints are available progressively. The [Hugging Face card](https://huggingface.co/VAST-AI/UniRig) says only the skeleton-prediction checkpoint is included and says skinning checkpoints are coming; however, the model repository file listing contains `skin/articulation-xl/model.ckpt`. The reviewed sources do not explain this discrepancy or establish which checkpoint is supported by the documented inference scripts. Treat UniRig as requiring an upstream smoke test before integration.

## SkinTokens / TokenRig (recommended candidate)

| Area | Verified from upstream |
|---|---|
| Source and status | [Official VAST-AI-Research/SkinTokens repository](https://github.com/VAST-AI-Research/SkinTokens/tree/273b691d35989d71cd17ff2895fdc735097b92d1), reviewed `main` commit. Maintainers call it UniRig’s successor. Its [model card](https://huggingface.co/VAST-AI/SkinTokens) identifies TokenRig and the FSQ-CVAE checkpoints and documents download/inference commands. |
| Software/model license | [Code license](https://github.com/VAST-AI-Research/SkinTokens/blob/273b691d35989d71cd17ff2895fdc735097b92d1/LICENSE) and [checkpoint model card](https://huggingface.co/VAST-AI/SkinTokens) declare MIT. The architecture fetches [Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B), whose model card declares Apache-2.0. No reviewed source grants comprehensive rights to all training assets: the checkpoint card reports training on ArticulationXL 2.0, VRoid Hub, and ModelsResource, while the processed training data is described as a separate/future release. Check those dataset and asset terms before commercial deployment; MIT metadata alone does not settle them. |
| Hardware / platform | README specifies Python >=3.11, CUDA Toolkit >=12.1, and NVIDIA GPU memory >=14 GB. This fits an H100 80 GB on stated memory requirements. It does not publish an OS support matrix. Its demo contains a Windows-specific subprocess branch, while installation and scripts are shell-oriented; Windows support is therefore not established end-to-end. |
| Dependencies / runtime shape | Requirements include `bpy>=4.2`, `trimesh`, `open3d`, `transformers>=4.57.0`, Lightning and others. `demo.py` launches `bpy_server.py` as a child process and sends mesh data to it; isolate its Python/CUDA/Blender dependencies from ComfyUI rather than installing this stack into ComfyUI’s environment. A complete transitive dependency license audit has not been done. |
| Inputs and outputs | `demo.py` accepts `.obj`, `.fbx`, `.glb`; CLI examples write `.glb`. Options support using an existing skeleton, transferring original texture/scale, and voxel-based skin postprocessing. This is an offline CLI/local Gradio workflow, not a ComfyUI node or HTTP provider. |
| Blender / Unity | It uses Blender’s Python module as a processing service and README documents a Blender export caveat: remove the `glTF_not_exported` node when importing results into Blender. No Unity plug-in or project integration is documented. Unity 6.6 documentation names FBX as its primary model-file format; GLB should be treated as requiring an explicit glTF importer or a tested conversion path. |
| Quality evidence / limitations | Authors’ README provides qualitative comparison imagery and reports 98–133% better skinning accuracy and 17–22% better bone prediction over baselines; these are author-reported claims, not independent tests. It also documents an optional voxel post-process. The repository does not provide a SlopForge-like acceptance guarantee or an automatic deformation-quality gate. |

## Recommendation for SlopForge #14

1. Keep a provider boundary and make TokenRig an opt-in provider running in its own environment/process. It is the more complete, current candidate and the H100 exceeds its published VRAM floor.
2. Preserve the original mesh and texture; request `--use_transfer`; expose `--use_postprocess` as a configurable quality option, not an unconditional fix. Keep original skeleton inputs available for corrective skin-only runs.
3. Validate the returned GLB structurally and produce review poses/evidence; require approval before marking a rig accepted. The upstream repo does not promise deformation quality for generated assets.
4. Add Unity delivery through FBX export or an explicitly selected glTF importer. Do not claim Unity compatibility solely because GLB was produced.
5. Before enabling commercial production by default, resolve training-data provenance/rights and audit dependency licenses. The reviewed MIT declarations cover project code/model-card labels, not necessarily third-party training content.

## Sources

- UniRig official repository and [README](https://github.com/VAST-AI-Research/UniRig/blob/6793c6640ff01c8fb389f3993434124bb43d2933/README.md), [license](https://github.com/VAST-AI-Research/UniRig/blob/6793c6640ff01c8fb389f3993434124bb43d2933/LICENSE), and [checkpoint files](https://huggingface.co/VAST-AI/UniRig/tree/main).
- UniRig authors’ [paper](https://arxiv.org/abs/2504.12451) and [project page](https://zjp-shadow.github.io/works/UniRig/).
- SkinTokens official [repository README](https://github.com/VAST-AI-Research/SkinTokens/blob/273b691d35989d71cd17ff2895fdc735097b92d1/README.md), [license](https://github.com/VAST-AI-Research/SkinTokens/blob/273b691d35989d71cd17ff2895fdc735097b92d1/LICENSE), [requirements](https://github.com/VAST-AI-Research/SkinTokens/blob/273b691d35989d71cd17ff2895fdc735097b92d1/requirements.txt), [demo](https://github.com/VAST-AI-Research/SkinTokens/blob/273b691d35989d71cd17ff2895fdc735097b92d1/demo.py), and [checkpoint card](https://huggingface.co/VAST-AI/SkinTokens).
- SkinTokens authors’ [paper](https://arxiv.org/abs/2602.04805); Qwen3-0.6B [model card/license metadata](https://huggingface.co/Qwen/Qwen3-0.6B).
- Unity 6.6 [model import documentation](https://docs.unity3d.com/6000.6/Documentation/Manual/ImportingModelFiles.html).
