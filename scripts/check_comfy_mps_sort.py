"""Run with ComfyUI's Python: python check_comfy_mps_sort.py [ComfyUI directory]."""
import sys
from pathlib import Path
import numpy as np
import torch

root = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / "ComfyUI"
sys.path.insert(0, str(root))
from comfy.ldm.trellis2.flexgemm import TorchHashMap
from comfy_extras.nodes_mesh_postprocess import _nearest_voxel_sample_gpu, _trilinear_sample_sparse_gpu

if not torch.backends.mps.is_available():
    raise SystemExit("This regression check requires an Apple GPU")
keys = torch.arange(2**25, 2**25 + 1024, dtype=torch.long, device="mps")
values = torch.arange(1024, dtype=torch.int32, device="mps")
actual = TorchHashMap(keys, values).lookup_flat(keys)
assert torch.equal(actual.cpu(), values.cpu()), "MPS voxel hash lookup lost valid neighbors"
coords = np.column_stack((np.full(1024, 128), np.arange(1024) // 512, np.arange(1024) % 512)).astype(np.int32)
colors = np.column_stack((np.arange(1024) / 1024, np.full(1024, 0.4), np.full(1024, 0.7))).astype(np.float32)
positions = (coords.astype(np.float32) + 0.5) / 512 - 0.5
for sample in (_nearest_voxel_sample_gpu, _trilinear_sample_sparse_gpu):
    result, valid = sample(positions, coords, colors, 512)
    assert valid.all(), f"{sample.__name__} dropped valid material voxels"
    np.testing.assert_allclose(result, colors, atol=1e-5)
print("MPS voxel neighbor and material sampling checks passed")
