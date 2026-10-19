"""Vectorised nearest-surface colour lookup: garment texel positions -> source surface samples -> texture."""
import sys
import numpy as np
from scipy.spatial import cKDTree
data = np.load(sys.argv[1])
pos, used = data["positions"], data["used"]          # (N,3) world positions of used texels, (N,2) texel yx
samples, uvs = data["samples"], data["sample_uvs"]   # (M,3), (M,2)
color, rough = data["color"], data["rough"]          # source textures (H,W,4) / (H,W) or empty
reach = float(data["reach"])
dist, idx = cKDTree(samples).query(pos, k=1, distance_upper_bound=reach, workers=-1)
ok = np.isfinite(dist)
uv = uvs[np.where(ok, idx, 0)]
ch, cw = color.shape[:2]
px = np.clip((uv[:, 0] * (cw - 1)).astype(int), 0, cw - 1); py = np.clip((uv[:, 1] * (ch - 1)).astype(int), 0, ch - 1)
out_color = color[py, px]; out_color[~ok] = 0
out_rough = rough[np.clip((uv[:, 1] * (rough.shape[0] - 1)).astype(int), 0, rough.shape[0] - 1),
                  np.clip((uv[:, 0] * (rough.shape[1] - 1)).astype(int), 0, rough.shape[1] - 1)] if rough.size else np.zeros(len(pos))
out_rough[~ok] = 0
np.savez(sys.argv[2], color=out_color.astype(np.float32), rough=out_rough.astype(np.float32), hit=ok)
print("NEAREST", int(ok.sum()), "of", len(pos))
