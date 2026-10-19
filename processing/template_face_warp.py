"""Warp a concept face onto a template face render with MediaPipe landmarks (piecewise affine).

Usage: template_face_warp.py concept.png template_render.png out_prefix face_landmarker.task
Writes out_prefix_warped.png (concept face in the template render's frame) and out_prefix_mask.png.
"""
import sys, json
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from scipy.spatial import Delaunay

concept_path, template_path, out = sys.argv[1:4]
model = sys.argv[4]  # MediaPipe face_landmarker.task (Apache-2.0), downloaded outside Git
detector = vision.FaceLandmarker.create_from_options(
    vision.FaceLandmarkerOptions(base_options=mp_python.BaseOptions(model_asset_path=model), num_faces=1))


def landmarks(path):
    image = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB)
    result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=image))
    if not result.face_landmarks:
        raise SystemExit(f"no face found in {path}")
    h, w = image.shape[:2]
    return np.array([[p.x * w, p.y * h] for p in result.face_landmarks[0]], np.float32), image


src_pts, src = landmarks(concept_path)
dst_pts, dst = landmarks(template_path)
h, w = dst.shape[:2]
warped = np.zeros_like(dst, np.float32)
for tri in Delaunay(dst_pts).simplices:
    d, s = dst_pts[tri], src_pts[tri]
    x, y, bw, bh = cv2.boundingRect(d)
    if bw == 0 or bh == 0:
        continue
    m = cv2.getAffineTransform((s).astype(np.float32), (d - [x, y]).astype(np.float32))
    patch = cv2.warpAffine(src, m, (bw, bh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    mask = np.zeros((bh, bw), np.uint8)
    cv2.fillConvexPoly(mask, np.int32(d - [x, y]), 1)
    region = warped[y:y + bh, x:x + bw]
    hh, ww = region.shape[:2]  # triangles touching the frame edge are clipped
    keep = mask[:hh, :ww] > 0
    region[keep] = patch[:hh, :ww][keep]
hull = cv2.convexHull(dst_pts.astype(np.int32))
mask = np.zeros((h, w), np.uint8)
cv2.fillConvexPoly(mask, hull, 255)
feather = int(0.03 * w) | 1
mask = cv2.erode(mask, np.ones((feather, feather), np.uint8))
mask = cv2.GaussianBlur(mask, (feather * 2 + 1, feather * 2 + 1), 0)
cv2.imwrite(out + "_warped.png", cv2.cvtColor(warped.astype(np.uint8), cv2.COLOR_RGB2BGR))
cv2.imwrite(out + "_mask.png", mask)
# Skin tone of the concept face (cheeks/forehead region) for matching the rest of the body.
inner = mask > 200
print(json.dumps({"landmarks": len(dst_pts), "face_mean_rgb": warped[inner].mean(axis=0).round(1).tolist(),
                  "template_mean_rgb": dst[inner].mean(axis=0).round(1).tolist()}))
