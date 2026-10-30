"""B6's bake (AI motion sources plan, B9; docs/CREATURES.md, "Extraction and bake"): an Action that video2rig's
import_motion put on a creature's rig, measured, made in place, cut to its loop and exported for Unity.

    blender <source.blend> --background --factory-startup --python blender/bake_extracted_motion.py -- request.json

The request names the legs (each leg's last two bones: the foot is the lower of their tails), the root bone, the fit
bones, the FBX, the baked .blend, the review renders and the report. Every key of the Action is sampled in world
space, and slopforge.creature_gait measures plants, period, stride and the loop window. The root's horizontal travel
is removed (the owner's D9: a delivered clip is in place, and the Unity Generic controller moves the creature at
stride / period). The Action is cut to its whole cycles, and the armature is exported as FBX with the rig's settings.
The window is rendered through the creature's start cameras for the review sheet.
"""
import json
import os
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.append(os.environ.get("SLOPFORGE_PACKAGE_ROOT", str(Path(__file__).resolve().parents[1])))
from slopforge.creature_gait import PLANT, GaitError, gait, in_place, loop_window  # noqa: E402


def fcurves(action):
    """Every F-curve of an action: Blender 4.x action.fcurves; 5.x keeps them in layers / strips / channelbags."""
    curves = getattr(action, "fcurves", None)
    if curves is not None:
        return list(curves)
    return [curve for layer in action.layers for strip in layer.strips for bag in strip.channelbags
            for curve in bag.fcurves]


def sample(scene, rig, keys, legs, root, bones):
    feet, roots, rotations = {leg: [] for leg in legs}, [], []
    for key in keys:
        scene.frame_set(int(key), subframe=key - int(key))
        for leg, names in legs.items():
            feet[leg].append(min((rig.matrix_world @ rig.pose.bones[name].tail).z for name in names))
        roots.append(list(rig.matrix_world @ rig.pose.bones[root].head))
        rotations.append([list(rig.pose.bones[name].rotation_quaternion) for name in bones])
    return {leg: np.array(values) for leg, values in feet.items()}, np.array(roots), np.array(rotations)


def remove_travel(scene, rig, keys, root, before, after):
    """Re-key the root bone's location so its head follows `after` (world) instead of `before`, in the bone's own
    axes (video2rig keys root_location there); the keys stay linear, as import_motion made them."""
    bone = rig.pose.bones[root]
    to_local = (rig.matrix_world.to_3x3() @ bone.bone.matrix_local.to_3x3()).inverted()
    for key, old, new in zip(keys, before, after):
        scene.frame_set(int(key), subframe=key - int(key))
        bone.location = bone.location + to_local @ Vector(new - old)
        bone.keyframe_insert("location", frame=float(key))
    for curve in fcurves(rig.animation_data.action):
        if curve.data_path == f'pose.bones["{root}"].location':
            for point in curve.keyframe_points:
                point.interpolation = "LINEAR"


def stance_slide(feet_xy, lifts, times, velocity):
    """Median horizontal speed (m/s) of planted feet once the controller moves the in-place clip at `velocity`: a
    foot that stays where it was set down slides at 0."""
    slides = []
    for leg, xy in feet_xy.items():
        speed = np.linalg.norm(np.diff(xy, axis=0) / np.diff(times)[:, None] + velocity, axis=1)
        planted = (lifts[leg][1:] < PLANT) & (lifts[leg][:-1] < PLANT)
        slides.extend(speed[planted])
    return float(np.median(slides)) if slides else None


def camera(scene, view):
    """An orthographic camera as cameras.json records it (right, up, forward; ortho height across the taller side)."""
    data = bpy.data.cameras.new(view["name"])
    data.type = "ORTHO"
    data.ortho_scale = max(view["ortho_width"], view["ortho_height"])
    obj = bpy.data.objects.new(view["name"], data)
    scene.collection.objects.link(obj)
    right, up, forward = (Vector(view[key]) for key in ("right", "up", "forward"))
    obj.matrix_world = Matrix.Translation(Vector(view["location"])) @ Matrix(
        [list(right) + [0], list(up) + [0], list(-forward) + [0], [0, 0, 0, 1]]).transposed()
    return obj


def render(scene, request, frames):
    cameras = json.loads(Path(request["cameras"]).read_text())
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.film_transparent = False
    world = scene.world or bpy.data.worlds.new("review")
    scene.world = world
    world.color = (0.35, 0.35, 0.35)
    sun = bpy.data.objects.new("review_sun", bpy.data.lights.new("review_sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (0.8, 0.0, 0.6)
    scene.collection.objects.link(sun)
    out = Path(request["renders"])
    out.mkdir(parents=True, exist_ok=True)
    images = []
    for view in cameras["views"]:
        scene.camera = camera(scene, view)
        scene.render.resolution_x = round(view["width_px"] * request.get("render_scale", 0.5))
        scene.render.resolution_y = round(view["height_px"] * request.get("render_scale", 0.5))
        for index, key, clip_frame in frames:
            scene.frame_set(int(key), subframe=key - int(key))
            scene.render.filepath = str(out / f"{view['name']}_{index if index == 'seam' else f'{index:02d}'}.png")
            bpy.ops.render.render(write_still=True)
            images.append({"view": view["name"], "index": index, "clip_frame": clip_frame,
                           "path": scene.render.filepath})
    return images


def run(request):
    scene = bpy.context.scene
    rigs = [obj for obj in scene.objects if obj.type == "ARMATURE"]
    if len(rigs) != 1:
        raise ValueError(f"the source .blend must hold one armature, found {len(rigs)}")
    rig = rigs[0]
    action = rig.animation_data.action if rig.animation_data else None
    if action is None:
        raise ValueError("the armature has no Action: import_motion put none on it")
    root, bones, legs = request["root_bone"], request["fit_bones"], request["legs"]
    missing = sorted({root, *bones, *(name for names in legs.values() for name in names)} - set(rig.pose.bones.keys()))
    if missing:
        raise ValueError(f"the rig lacks bones the motion names: {', '.join(missing)}")
    location = f'pose.bones["{root}"].location'
    keys = sorted({round(point.co.x, 4) for curve in fcurves(action) if curve.data_path == location
                   for point in curve.keyframe_points})
    if len(keys) < 2:
        raise ValueError(f"the Action keys the root {root} {len(keys)} times; import_motion keys every clip frame")
    fps = scene.render.fps / scene.render.fps_base
    times = (np.array(keys) - keys[0]) / fps           # import_motion keys the clip's real times at the scene's rate
    clip = np.asarray(request["times"], float)
    if len(keys) != len(clip) or np.abs(times - (clip - clip[0])).max() > 0.5 / fps:
        raise ValueError(f"the Action's {len(keys)} keys are not the clip's frame times ({len(clip)} frames at "
                         f"{1 / np.median(np.diff(clip)):.3g} fps): import_motion did not key the fit's times")
    corners = [obj.matrix_world @ Vector(corner) for obj in scene.objects if obj.type == "MESH"
               for corner in obj.bound_box]
    height = max(c.z for c in corners) - min(c.z for c in corners)

    feet, before, rotations = sample(scene, rig, keys, legs, root, bones)
    measured = gait(feet, times, height, root=before)
    # the loop's ends on keys at whole scene frames: the FBX export bakes whole frames, so it delivers this window
    whole = np.abs(np.array(keys) - np.round(keys)) < 1e-3
    window = loop_window(rotations, times, measured["period_s"], allowed=whole)
    start, end = window["start"], window["end"]
    after, _ = in_place(before, times)
    span = slice(start, end + 1)
    velocity = np.polyfit(times[span] - times[start], before[span, :2], 1)[0]   # the delivered window's own speed
    speed = float(np.hypot(*velocity))

    remove_travel(scene, rig, keys, root, before, after)
    _, baked, _ = sample(scene, rig, keys, {}, root, [])
    lifts, feet_xy = {}, {leg: [] for leg in legs}
    for key in keys[span]:
        scene.frame_set(int(key), subframe=key - int(key))
        for leg, names in legs.items():
            feet_xy[leg].append(min((rig.matrix_world @ rig.pose.bones[name].tail for name in names),
                                    key=lambda point: point.z).xy[:])
    for leg, heights in feet.items():
        lifts[leg] = (heights[span] - np.percentile(heights, 10)) / height
    slide = stance_slide({leg: np.array(xy) for leg, xy in feet_xy.items()}, lifts, times[span], velocity)
    direction = velocity / speed if speed else np.zeros(2)
    surge = baked[span, :2] @ direction

    scene.frame_start, scene.frame_end = int(round(keys[start])), int(round(keys[end]))
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    Path(request["fbx"]).parent.mkdir(parents=True, exist_ok=True)
    # the rig FBX's settings (blender/creature_rig.py), with the Action baked over the window
    bpy.ops.export_scene.fbx(filepath=request["fbx"], use_selection=True, object_types={"ARMATURE"},
                             add_leaf_bones=False, bake_anim=True, bake_anim_use_nla_strips=False,
                             bake_anim_use_all_actions=False, bake_anim_force_startend_keying=True,
                             bake_anim_step=1.0, bake_anim_simplify_factor=0.0)
    count = request.get("samples", 8)   # one cycle's phases, from the window's start
    picks = [int(np.argmin(np.abs(times - (times[start] + k * measured["period_s"] / count)))) for k in range(count)]
    # and the loop's seam: the window's last frame, shown beside its first in the review sheet
    shots = [(index, keys[k], k) for index, k in enumerate(picks)] + [("seam", keys[end], end)]
    images = render(scene, request, shots) if request.get("renders") else []
    bpy.ops.wm.save_as_mainfile(filepath=request["blend"], copy=True)
    return {"status": "complete", "fps": fps, "keys": len(keys), "height_m": round(height, 4),
            "plants": measured["plants"], "cycles": measured["cycles"], "period_s": measured["period_s"],
            "weak_legs": measured["weak_legs"],
            "speed_mps": round(speed, 4), "velocity": [round(float(v), 4) for v in velocity],
            "stride_m": round(speed * measured["period_s"], 4),
            "window": {**window, "start_frame": scene.frame_start, "end_frame": scene.frame_end,
                       "start_s": round(float(times[start]), 4), "end_s": round(float(times[end]), 4),
                       "seam_root_m": round(float(np.linalg.norm(baked[end, :2] - baked[start, :2])), 4)},
            "residual_travel_m": round(float(np.ptp(surge)), 4),
            "stance_slide_mps": None if slide is None else round(slide, 4),
            "bones": sorted(bone.name for bone in rig.pose.bones), "renders": images}


def main():
    request = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
    try:
        report = run(request)
    except GaitError as exc:
        report = {"status": "error", "errors": [str(exc)], "failure_code": exc.code, "measured": exc.measured}
    except Exception as exc:  # noqa: BLE001 - the report carries every failure to the pipeline
        report = {"status": "error", "errors": [f"{type(exc).__name__}: {exc}"], "traceback": traceback.format_exc()}
    Path(request["report"]).write_text(json.dumps(report, indent=1))


main()
