"""Optional ComfyUI node: preserve TRELLIS texture boundaries for controlled diagnosis."""

import hashlib
import json
from pathlib import Path

import folder_paths
import torch
from comfy_api.latest import ComfyExtension, IO


def describe(tensor):
    value = tensor.detach().float().cpu()
    channels = value.reshape(-1, value.shape[-1])
    return {
        "shape": list(tensor.shape), "dtype": str(tensor.dtype),
        "finite": bool(torch.isfinite(value).all()),
        "min": channels.amin(0).tolist(), "max": channels.amax(0).tolist(),
        "mean": channels.mean(0).tolist(),
        "zero_fraction": (channels == 0).float().mean(0).tolist(),
    }


def latent_snapshot(latent):
    return {key: value.detach().cpu() if torch.is_tensor(value) else value
            for key, value in latent.items()}


class SlopForgeTextureDiagnostics(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="SlopForgeTextureDiagnostics", category="SlopForge/diagnostics",
            is_output_node=True,
            inputs=[IO.Voxel.Input("voxel_colors"), IO.Mesh.Input("mesh"),
                    IO.Latent.Input("shape_samples"), IO.Latent.Input("texture_samples"),
                    IO.Custom("SHAPE_SUBDIVIDES").Input("shape_subdivides"),
                    IO.Image.Input("loaded_image"), IO.Image.Input("cropped_image"),
                    IO.String.Input("filename_prefix", default="texture_diagnostic")],
            outputs=[],
        )

    @classmethod
    def execute(cls, voxel_colors, mesh, shape_samples, texture_samples,
                shape_subdivides, loaded_image, cropped_image, filename_prefix):
        # Diagnostics are opt-in and stay outside the generated asset's approval flow.
        if Path(filename_prefix).name != filename_prefix or filename_prefix in ("", ".", ".."):
            raise ValueError("Diagnostic filename_prefix must be a filename, without a directory")
        directory = Path(folder_paths.get_output_directory()) / "slopforge_diagnostics"
        directory.mkdir(exist_ok=True)
        coords = voxel_colors.data.detach().cpu()
        report = {
            "resolution": int(voxel_colors.resolution),
            "voxel_coords": describe(coords), "voxel_colors": describe(voxel_colors.voxel_colors),
            "voxel_coords_sha256": hashlib.sha256(coords.numpy().tobytes()).hexdigest(),
            "mesh_vertices": describe(mesh.vertices), "loaded_image": describe(loaded_image),
            "cropped_image": describe(cropped_image),
            "shape_samples": describe(shape_samples["samples"]),
            "texture_samples": describe(texture_samples["samples"]),
            "shape_metadata": {key: shape_samples.get(key) for key in ("model_frame", "coord_resolution")},
            "texture_metadata": {key: texture_samples.get(key) for key in ("model_frame", "coord_resolution")},
            "subdivisions": [{"coords": describe(sub.coords), "features": describe(sub.feats)}
                             for sub in shape_subdivides],
        }
        payload = {
            "voxel_coords": coords, "voxel_colors": voxel_colors.voxel_colors.detach().cpu(),
            "resolution": int(voxel_colors.resolution),
            "mesh_vertices": mesh.vertices.detach().cpu(),
            "shape_samples": latent_snapshot(shape_samples),
            "texture_samples": latent_snapshot(texture_samples),
            "subdivisions": [{"coords": sub.coords.detach().cpu(), "feats": sub.feats.detach().cpu(),
                              "shape": sub.shape, "scale": sub._scale} for sub in shape_subdivides],
            "loaded_image": loaded_image.detach().cpu(), "cropped_image": cropped_image.detach().cpu(),
        }
        torch.save(payload, directory / (filename_prefix + ".pt"))
        (directory / (filename_prefix + ".json")).write_text(json.dumps(report, indent=2) + "\n")
        return IO.NodeOutput()


class SlopForgeDiagnosticsExtension(ComfyExtension):
    async def get_node_list(self):
        return [SlopForgeTextureDiagnostics]


async def comfy_entrypoint():
    return SlopForgeDiagnosticsExtension()
