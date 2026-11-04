#!/usr/bin/env python3
"""A character built from a separate head and a headless body. docs/CHARACTER-RIGGING.md, "Characters built in parts".

The steps, each run by hand with a review between them, because results vary a lot by seed and input:

  images  repaint the approved concept into straight-on head close-ups, and edit the head off it for headless bodies
  build   one image to one 3D model
  hair    repaint a built head's face and hair from renders of itself, and set the result as the brief's head_base
  paint   optionally, repaint a built body whose colour came out blotchy, and set the result as the brief's body_base
  join    a chosen head and body into one figure on one material
  rig     Rigify with the long-coat fixes, then a Unity-ready FBX
  walk    retarget a clip onto the rig, as a blend to review
  unity   the rigged figure in a Unity project as a Humanoid prefab
  gear    a shared clip library, then a pack and weapon mounted as <name>_equipped.prefab

The brief is a JSON file: name, person ("old woman"), their ("her"), they_are ("she is"), who, eyes, hair, clothes, surfaces, style (the art style, which every painting prompt repeats), height in metres, concept (the approved image, which sets the head's size), and optionally long_skirt, grade (RGB gains on the body's non-brass colour), head_base (the repainted head colour map from `hair`, which `join` needs), stump_neck (how the edit leaves the neck), back_of_head (how to paint the back of the hair or head covering), body_base (a repainted body colour map), body_smooth (passes taking the generator's lumps out of the body's surface), leg_swing ([thigh, knee], scaling how far the legs swing, for a long skirt or a heavy body), arm_drop (0 to 1, how far the arms can lower, for a wide body), keep_contacts (don't cut hands from hips, when arm_drop keeps them near their modelled pose and the cut only leaves holes).
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
Image.MAX_IMAGE_PIXELS = None

SEEDS = (16505, 16606, 16707, 16808, 16909, 17010)
SHEET = 4096
HEAD_NORMAL = 0.5
FLAT = ("The light is flat and even from every side, with no cast shadows")
HEAD_PROMPT = ("Paint the same {person} as in this reference image, keeping who {they_are}: {who}. Now show {their} head and "
               "bare neck only, facing the camera exactly straight on, perfectly level and symmetrical, like a passport "
               "photograph, filling the frame from the top of {their} head to the base of {their} neck. Eyes open and looking "
               "straight ahead, mouth closed. {hair} No collar, no clothes, no jewellery, nothing below the neck. " + FLAT +
               ", no dark eye sockets and no shine, because this painting becomes the skin of a 3D model. A plain mid-grey "
               "background. {style}")
# Takes only the head off, so the 3D step sees a solid neck and the concept's own colours and light. Erasing the neck too made
# it build a hollow shell with a void at the collar, and repainting in flat light lost the colours (2026-11-03).
STUMP_PROMPT = ("Edit this picture and change one thing only: take off this {person}'s head at the neck, so that the picture shows a "
                "headless figure. {stump_neck} Nothing at all is above the cut, only the same plain background. Everything else stays "
                "exactly as it is in this picture: the same clothes, the same colours, the same materials, the same light and shading, "
                "the same pose, the same size and the same place in the frame.")


STUMP_NECK = "A short thick bare neck rises out of the collar and ends in a flat level cut just below where the chin was, in plain skin colour."


def brief_prompts(brief):
    return {"head": HEAD_PROMPT.format(**brief), "body": STUMP_PROMPT.format(**{"stump_neck": STUMP_NECK, **brief})}


def brass_mask(rgb):
    """Polished brass by colour. A direct model run skips the material check, and one body came back 98.5% metal."""
    top = rgb.max(2)
    saturation = (top - rgb.min(2)) / np.maximum(top, 1)
    # Yellow, not orange: at 0.68 a bright leather forearm guard counted as brass and stayed ungraded and metal.
    return (top > 110) & (saturation > 0.42) & (rgb[..., 1] > rgb[..., 0] * 0.74) & (rgb[..., 2] < rgb[..., 1] * 0.72)


def metal_brass(rgb, metal):
    """Brass by colour where the generator's metal map agrees. Warm lit skin has brass's colour: a neck and the backs of the hands
    came out as shiny orange flecks, and the map held the buckle, loops and toe caps and none of the skin. `metal` is 0 to 255."""
    return brass_mask(rgb) & (metal > 76)


def head_measures(concept, body):
    """From the cut-outs of a concept and of its edit with the head off, in one frame: the body's share of the figure's height,
    and the skull's width as a share of it, measured just under the crown of the concept."""
    rows = np.where(concept.any(1))[0]
    crown, floor = int(rows.min()), int(rows.max())
    height = floor - crown
    near_top = range(crown + round(0.03 * height), crown + round(0.1 * height))
    widths = [np.ptp(np.where(concept[row])[0]) for row in near_top if concept[row].any()]
    return (floor - int(np.where(body.any(1))[0].min())) / height, float(np.median(widths)) / height


def rear_weight(facing, used):
    """1 on surfaces facing away from the concept's camera (-Y). Its front-on painting leaks buttons round the sides there."""
    weight = np.zeros_like(facing, dtype=float)
    weight[used] = np.clip((facing[used] + 0.35) / 0.3, 0, 1)
    return weight


def body_maps(native, facing_path, grade=None, painted=None):
    """Colour, metal and roughness for the body: only brass is metal, and nothing else shines, because leather at
    roughness 0.49 read as PVC. Surfaces facing away keep the model's own voxel colour. A body repainted all round
    (`painted`) already has its own rear."""
    base = np.asarray(Image.open(painted or native / "basecolor.png").convert("RGB"), float)
    voxel = base if painted else np.asarray(Image.open(native / "basecolor_voxel.png").convert("RGB"), float)
    size = base.shape[0]
    facing = np.load(facing_path)
    rear = rear_weight(facing["facing"], facing["used"])
    weight = np.asarray(Image.fromarray((rear * 255).astype("uint8")).resize((size, size), Image.BILINEAR)
                        .filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(3)), float)[..., None] / 255
    metallic = native / "metallic.png"
    found = metal_brass(base, np.asarray(Image.open(metallic).convert("L").resize((size, size)), float)) if metallic.exists() else brass_mask(base)
    brass = found & (weight[..., 0] < 0.5)
    gain = np.array(grade if grade else (1, 1, 1), float)
    colour = np.where(brass[..., None], base, (base * (1 - weight) + voxel * weight) * gain)
    metal = (brass * 255).astype("uint8")
    roughness = np.asarray(Image.open(native / "roughness.png").convert("L").resize((size, size)), float)
    roughness = np.where(brass, np.minimum(roughness, 102), np.maximum(roughness, 191)).astype("uint8")
    return (Image.fromarray(np.clip(colour, 0, 255).astype("uint8")), Image.fromarray(metal), Image.fromarray(roughness))


def compose_sheet(body, head, mode="RGB", fill=0):
    """The body in the bottom left two thirds and the head in the top right third, matching join_character_parts.py."""
    large = round(SHEET * 2 / 3)
    sheet = Image.new(mode, (SHEET, SHEET), fill)
    sheet.paste(body.convert(mode).resize((large, large), Image.LANCZOS), (0, SHEET - large))
    sheet.paste(head.convert(mode).resize((SHEET - large, SHEET - large), Image.LANCZOS), (large, 0))
    return sheet


def blender():
    from slopforge.paths import blender_executable
    return blender_executable()


def run_blender(script, *arguments, log=None):
    done = subprocess.run([str(blender()), "--background", "--python-exit-code", "1", "--python", str(ROOT / "blender" / script),
                           "--", *map(str, arguments)], capture_output=True, text=True)
    if log:
        Path(log).write_text(done.stdout + done.stderr)
    if done.returncode:
        raise SystemExit(f"{script} failed:\n{done.stdout[-2000:]}\n{done.stderr[-1000:]}")


def edit(client, workflow, source, prompt, seed, destination, denoise=1.0):
    graph = json.loads(json.dumps(workflow))
    graph["sampler"]["inputs"]["denoise"] = denoise
    uploaded = client.upload_file(source)
    graph["image"]["inputs"]["image"] = "/".join(part for part in (uploaded.get("subfolder"), uploaded["name"]) if part)
    graph["positive"]["inputs"]["prompt"] = prompt
    graph["sampler"]["inputs"]["seed"] = seed
    prompt_id = client.queue_workflow(graph)
    history = client.wait_for_completion(prompt_id)
    client.download_output(client.list_outputs(history)[0], destination)


def images(args, brief):
    from slopforge.backends.comfyui import ComfyUIClient
    client = ComfyUIClient(os.environ["COMFYUI_URL"])
    workflow = json.loads((ROOT / "workflows/image_edit_qwen_api.json").read_text())
    prompts = brief_prompts(brief)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for kind, source in (("head", args.head_source), ("body", args.body_source)):
        if not source:
            continue
        done = []
        for take, seed in enumerate(SEEDS[:args.takes], 1):
            destination = out / f"{kind}-{take}.png"
            edit(client, workflow, source, prompts[kind], seed, destination)
            done.append(destination)
            print(destination, "seed", seed, flush=True)
        width = 420
        sheet = Image.new("RGB", (width * 3, (width + 22) * ((len(done) + 2) // 3)), (28, 23, 18))
        draw = ImageDraw.Draw(sheet)
        for index, path in enumerate(done):
            x, y = (index % 3) * width, (index // 3) * (width + 22)
            sheet.paste(Image.open(path).convert("RGB").resize((width, width), Image.LANCZOS), (x, y + 22))
            draw.text((x + 6, y + 5), f"Take {index + 1}", fill=(239, 227, 200))
        sheet.save(out / f"{kind}-sheet.png")


def build_command(image, part, out, seed):
    """The 3D step. Midpoint reduction sends Blender the detail mesh, and hidden faces go before it reduces: a generated surface is a
    double skin, whose hidden wall took most of a body's faces and texture at the character graph's own reduction (2026-11-03)."""
    inputs = {"crop": {"pad_factor": 1.1}, "shape_upsample_stage": {"target_resolution": 1536}, "maps": {"texture_size": 4096},
              "shape_decimate": {"placement_mode": "midpoint"}}
    return [sys.executable, str(ROOT / "processing/comfy_generate_3d.py"), "--image", str(image), "--name", part,
            "--dest", str(out / f"{part}.glb"), "--seed", str(seed), "--metadata", str(out / "generation.json"),
            "--workflow", str(ROOT / "workflows/trellis2_image_to_model_h100_character_api.json"),
            "--face-budget", "60000" if part == "body" else "30000", "--voxel-resolution", "256", "--blender", str(blender()),
            "--remove-hidden-faces", "--project-concept", "--quality", '{"tier":"final","settings":{}}',
            "--workflow-inputs", json.dumps(inputs), "--failure-report", str(out / "failure.json")]


def build(args, brief):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / "processing/prepare_3d_input.py"), "--input", args.image, "--cutout", str(out / "cut-raw.png"),
                    "--output", str(out / "flat.png")], check=True)
    cut = Image.open(out / "cut-raw.png").convert("RGBA")
    cut.crop(cut.getchannel("A").getbbox()).save(out / "cut.png")
    subprocess.run(build_command(out / "cut.png", args.part, out, args.seed), check=True, cwd=ROOT)


REAR_ANGLES = (180, 135, -135, 90, -90)
HAIR_PROMPT = ("Repaint this exact head from this same angle and in this same place in the frame, on the same plain grey background. "
               "The face, ears and neck stay as they are. Paint the hair or head covering properly: {hair} {back}, covering the "
               "whole back and sides of the skull with no bare patches, holes or skin showing through. Flat even light with no "
               "shadows. {style}")
BODY_ANGLES = (0, 60, -60, 120, -120)  # not 180: straight from behind the edit paints the front's apron on the back
BODY_PAINT_PROMPT = ("Repaint this exact headless figure from this same angle and in this same place in the frame, on the same plain grey "
                     "background. Every part stays exactly where it is and the same size. Keep every part of {their} clothing: {clothes}. "
                     "{surfaces}. The colours are even, with no blotches, stains or dark patches. Flat even light with no shadows. {style}")


def aligned_colour(projected, voxel, used, radius=48):
    """The model's own colour, which sits exactly on its shape, in the tone of the projected concept.

    A front-on painting projected onto a sculpted head doesn't line up: the painted nose and eyes sit off the sculpted
    ones, a dark band ran down one side of a nose, and the mismatch reads as warping when the head turns. So only the
    painting's broad colour is kept, as a smooth ratio. Arrays are RGB floats of one size; `used` masks the sheet's texels."""
    mask = Image.fromarray((used * 255).astype("uint8"))
    blur = lambda image: np.asarray(image.filter(ImageFilter.GaussianBlur(radius)), float)
    weight = np.maximum(blur(mask) / 255, 1e-3)[..., None]

    def soft(array):
        masked = np.where(used[..., None], array, 0).astype("uint8")
        return np.stack([blur(Image.fromarray(masked[..., channel])) for channel in range(3)], 2) / weight

    return np.clip(voxel * np.clip(soft(projected) / np.maximum(soft(voxel), 1), 0.4, 2.5), 0, 255)


def flatten_normals(normal, strength):
    """A normal map scaled toward flat, as an RGB uint8 array. At full strength a head's map carved hard rings round the eyes."""
    vectors = normal.astype(float) / 127.5 - 1
    vectors[..., :2] *= strength
    vectors /= np.maximum(np.linalg.norm(vectors, axis=2, keepdims=True), 1e-6)
    return np.clip((vectors + 1) * 127.5, 0, 255).astype("uint8")


FACE_ANGLES = (0, 40, -40)
FACE_PROMPT = ("Repaint this exact face from this same angle and in this same place in the frame, on the same plain grey background. "
               "Every feature stays exactly where it is and the same size: the nose, the mouth, the ears, the hairline and the "
               "eye sockets. This is the same {person}: {who}. {eyes} Skin is even, matte and weathered, with no shiny patches and no "
               "blotches of colour. {hair} Flat even light with no shadows. {style}")


def project_head_views(colour, texels, views, paintings, face=False):
    """Paint a head's rendered views back onto the sheet, blended by the angle round the head. Each painting draws its own hairline, and
    choosing one view per texel by the generated normal, which flips strand by strand, tore it. With `face`, the front of the head and
    a little past its middle. Otherwise the back, fading in across the middle over that. A test for which pixels were hair left flecks
    at the nape and raw colour through thinning hair, so a head's back takes the whole painting. The crown faces no level view and is
    left for paint_crown. Returns the new sheet as an array, and the texels it changed."""
    position, normal, used = texels["position"], texels["normal"], texels["used"]
    centre, extent = np.array(views["centre"]), views["extent"]
    round_head = np.degrees(np.arctan2(position[..., 0] - centre[0], centre[1] - position[..., 1]))
    behind = position[..., 1] > centre[1]
    # A hard split left a line down the side of the head. The face reaches past the middle, and the back fades in over it.
    across = (position[..., 1] - centre[1]) / (0.1 * extent)
    fade = np.clip(1.5 - across, 0, 1) if face else np.clip(across + 0.5, 0, 1)
    region = fade > 0
    height = position[..., 2]
    level = ~((height > np.percentile(height[used], 85)) & (np.abs(normal[..., 2]) > 0.8))
    total, painted, shown = np.zeros(used.shape), np.zeros((*used.shape, 3)), np.zeros(used.shape)
    for angle, painting in paintings.items():
        radians = np.radians(angle)
        towards = np.array((np.sin(radians), -np.cos(radians), 0.0))
        right = np.array((np.cos(radians), np.sin(radians), 0.0))
        take = used & region & level & ((position - centre) @ towards > -0.16 * extent)
        offset = position[take] - centre
        size = painting.shape[0]
        columns = np.clip((((offset @ right) / extent + 0.5) * size).astype(int), 0, size - 1)
        rows = np.clip(((0.5 - offset[:, 2] / extent) * size).astype(int), 0, size - 1)
        pixels = painting[rows, columns].astype(float)
        gap = np.abs((round_head[take] - angle + 180) % 360 - 180)
        weight = np.exp(-(np.minimum(gap, 60) / 22) ** 4)  # one view holds until a few degrees either side of halfway
        alpha = fade[take]
        total[take] += weight
        shown[take] += weight * alpha
        painted[take] += pixels * (weight * alpha)[:, None]
    share = shown / np.maximum(total, 1e-30)
    changed = share > 0.02
    out = colour.astype(float).copy()
    out[changed] = out[changed] * (1 - share[changed, None]) + painted[changed] / shown[changed, None] * share[changed, None]
    return np.clip(out, 0, 255).astype(colour.dtype), changed


def project_views(colour, texels, views, paintings):
    """Paint a whole figure's rendered views back onto the sheet, blended by the angle round the body among the views that can see each
    texel. Choosing one view per texel by the generated normal, which flips from fold to fold, laid streaks of two different coats side
    by side. With no test for what a view can see, a fist in front of a coat printed itself on the coat behind, and its sleeve's back
    took the colour of its front. Returns the new sheet as an array, and the texels it changed."""
    position, used = texels["position"], texels["used"]
    centre, extent = np.array(views["centre"]), views["extent"]
    around = np.degrees(np.arctan2(position[..., 0] - centre[0], centre[1] - position[..., 1]))[used]
    offset = position[used] - centre
    total, painted = np.zeros(len(offset)), np.zeros((len(offset), 3))
    for angle, painting in paintings.items():
        radians = np.radians(angle)
        towards = np.array((np.sin(radians), -np.cos(radians), 0.0))
        right = np.array((np.cos(radians), np.sin(radians), 0.0))
        depth = offset @ towards
        at = lambda size: (np.clip(((0.5 - offset[:, 2] / extent) * size).astype(int), 0, size - 1),
                           np.clip((((offset @ right) / extent + 0.5) * size).astype(int), 0, size - 1))
        # What's nearest the view in each small cell of it. Generous enough for a surface seen at a slant, and less than an arm's gap from a coat.
        cell = at(256)
        nearest = np.full((256, 256), -np.inf)
        np.maximum.at(nearest, cell, depth)
        # It also stops a little past the figure's middle, or it paints through a gap onto the far side: an apron reached a man's back.
        sees = (depth > nearest[cell] - 0.012 * extent) & (depth > -0.05 * extent)
        pixel = at(painting.shape[0])
        weight = np.exp(-(np.minimum(np.abs((around - angle + 180) % 360 - 180), 60) / 22) ** 4) * (sees & ~backdrop(painting)[pixel])
        total += weight
        painted += painting[pixel].astype(float) * weight[:, None]
    changed, out = np.zeros(used.shape, bool), colour.copy()
    hit = total > 1e-30
    changed[used] = hit
    seen = np.zeros((*used.shape, 3))
    seen[used] = painted / np.maximum(total, 1e-30)[:, None]
    out[changed] = seen[changed]
    return out, changed


def backdrop(painting):
    """The plain grey behind a painted figure, widened a little. The figure's outline moves from the render's, so a texel at its edge
    could land on the backdrop. A painting with no grey in its corners has no backdrop to find."""
    corners = np.concatenate([painting[:len(painting) // 8, :len(painting) // 8].reshape(-1, 3), painting[:len(painting) // 8, -len(painting) // 8:].reshape(-1, 3)])
    grey = np.median(corners, 0)
    if grey.max() - grey.min() > 12:
        return np.zeros(painting.shape[:2], bool)
    plain = np.abs(painting.astype(float) - grey).max(2) < 14
    # Only grey reaching the edge of the frame: a highlight on leather can be the same grey, and dropping it left flakes of raw colour.
    regions, _ = ndimage.label(plain)
    outer = np.isin(regions, np.setdiff1d(np.concatenate([regions[0], regions[-1], regions[:, 0], regions[:, -1]]), [0]))
    return np.asarray(Image.fromarray((outer * 255).astype("uint8")).filter(ImageFilter.MaxFilter(5))) > 127


def neck_skin(colour, texels):
    """The bare neck of a headless body, in the generator's own bright warm colour at the top of the figure. The paintings show an empty
    collar, so they have no neck to give, and it came back in blocks. `match_skin` grades it to the face afterwards."""
    used, height = texels["used"], texels["position"][..., 2]
    hsv = np.asarray(Image.fromarray(colour.astype("uint8")).convert("HSV"), float)
    return used & (height > height[used].max() - 0.1) & (hsv[..., 0] < 0.14 * 255) & (hsv[..., 1] > 0.3 * 255) & (hsv[..., 2] > 120)


def body_normal(body_dir, brief):
    """The body's normal map, or a flat one for a smoothed body: the generator's map carries the lumps the smoothing took out."""
    normal = Image.open(body_dir / "native_material/normal.png").convert("RGB")
    return Image.new("RGB", normal.size, (128, 128, 255)) if brief.get("body_smooth") else normal


def view_note(angle, body=False):
    """Says which side a view shows. Without it the edit put a face on the back of a head and an apron on a man's back."""
    away = abs(angle)
    if body:
        return ("This is the back of the figure, seen from behind: only the backs of the clothes show, and anything worn on the "
                "front, such as an apron's bib, does not. " if away > 90 else "")
    if away > 100:
        return "This is the back of the head, seen from behind: no face, eyes, nose or mouth show here. "
    if away > 60:
        return "This is the side of the head in profile. "
    # Positive words only: "no mask, no blindfold" painted a thicker mask, because naming a thing primes the model.
    # And name the iris's colour: "pale whites and clear irises" painted blank white eyes.
    turned = "The head stays turned to the side exactly as it is in this picture, not towards the viewer. " if away else ""
    return turned + "Both eyes are open, with dark brown irises and black pupils, and bare skin on the lids and brow bones in the same tone as the cheeks. "


def paint_views(client, workflow, angles, prompt, seed, out, body=False):
    paintings = {}
    for angle in angles:
        painted = out / f"painted_{angle}.png"
        if not painted.exists():  # delete one to repaint it; the seed varies the result a lot
            edit(client, workflow, out / f"view_{angle}.png", view_note(angle, body) + prompt, seed, painted)
        paintings[angle] = np.asarray(Image.open(painted).convert("RGB").resize((1024, 1024), Image.LANCZOS))
        print(painted, flush=True)
    return paintings


def grow_paint(painted, changed, passes=4):
    """Spread painted texels over their neighbours, so the sheet's island edges and generated cracks between them don't
    keep the old colour: they showed as thin lines on a cheek. Returns the colour and mask, grown."""
    colour, mask = painted.astype(float), changed.copy()
    for _ in range(passes):
        total, count = np.zeros_like(colour), np.zeros(mask.shape)
        for axis, step in ((0, 1), (0, -1), (1, 1), (1, -1)):
            total += np.roll(colour * mask[..., None], step, axis)
            count += np.roll(mask, step, axis)
        new = ~mask & (count > 0)
        colour[new] = total[new] / count[new, None]
        mask |= new
    return colour, mask


def blend_in(colour, painted, changed):
    size = colour.size[0]
    painted, changed = grow_paint(painted, changed)
    mask = Image.fromarray((changed * 255).astype("uint8")).resize((size, size), Image.BILINEAR).filter(ImageFilter.GaussianBlur(2))
    return Image.composite(Image.fromarray(painted.astype("uint8")).resize((size, size), Image.LANCZOS), colour, mask)


def hair(args, brief):
    """Repaint a built head from renders of itself, so every painted feature sits on its sculpted one: the model's own
    colour in the concept's tone is rendered flat, its face is repainted from the front and sides, and its hair from behind.
    The 3D step invents what a front concept can't show, and the concept's own face doesn't line up with the shape."""
    from slopforge.backends.comfyui import ComfyUIClient
    build, out = Path(args.head), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    native = build / "native_material/basecolor.png"
    voxel = Image.open(build / "native_material/basecolor_voxel.png").convert("RGB")
    size = voxel.size[0]
    half = (size // 2, size // 2)
    run_blender("character_view.py", model_in(build, "head"), native, out, 1024, *REAR_ANGLES, *FACE_ANGLES, log=out / "views.log")
    texels = np.load(out / "texels.npz")
    aligned = aligned_colour(np.asarray(Image.open(native).convert("RGB").resize(half, Image.LANCZOS), float),
                             np.asarray(voxel.resize(half, Image.LANCZOS), float), texels["used"]).astype("uint8")
    Image.fromarray(aligned).resize((size, size), Image.LANCZOS).save(out / "aligned.png")
    run_blender("character_view.py", model_in(build, "head"), out / "aligned.png", out, 1024, *FACE_ANGLES, log=out / "views.log")
    client = ComfyUIClient(os.environ["COMFYUI_URL"])
    workflow = json.loads((ROOT / "workflows/image_edit_qwen_api.json").read_text())
    views = json.loads((out / "views.json").read_text())
    seed = args.seed or SEEDS[0]
    colour = Image.fromarray(aligned)
    faces = paint_views(client, workflow, FACE_ANGLES, FACE_PROMPT.format(**brief), seed, out)
    painted, face_changed = project_head_views(aligned, texels, views, faces, face=True)
    colour = blend_in(colour, painted, face_changed)
    back = brief.get("back_of_head", "The same hair as at the front, the same length and colour, with a fine even texture and no separate locks")
    hairs = paint_views(client, workflow, REAR_ANGLES, HAIR_PROMPT.format(back=back, **brief), seed, out)
    painted, changed = project_head_views(np.asarray(colour), texels, views, hairs)
    colour = blend_in(colour, painted, changed)
    colour = blend_in(colour, *paint_crown(np.asarray(colour), face_changed | changed, texels))
    colour.resize((size, size), Image.LANCZOS).save(out / "basecolor-hair.png")
    print(out / "basecolor-hair.png")


def paint_crown(colour, changed, texels, size=96):
    """The top of a head from the painted surface round it, seen from above. Every repaint view is level, so a texel facing up faces
    none and kept the model's raw colour: a dark disc where a third-person camera looks down on the head. Returns the colour array
    and the texels it set."""
    position, normal, used = texels["position"], texels["normal"], texels["used"]
    height = position[..., 2]
    crown = used & ~changed & (height > np.percentile(height[used], 85)) & (np.abs(normal[..., 2]) > 0.5)
    out = colour.astype(float).copy()
    if not crown.any():
        return out, crown
    upper = used & changed & (height > np.percentile(height[used], 60))
    low, span = position[used][:, :2].min(0), max(np.ptp(position[used][:, :2], 0).max(), 1e-6)
    cells = lambda points: np.clip(((points[:, :2] - low) / span * (size - 1)).astype(int), 0, size - 1)
    total, count = np.zeros((size, size, 3)), np.zeros((size, size))
    columns, rows = cells(position[upper]).T
    np.add.at(total, (rows, columns), out[upper])
    np.add.at(count, (rows, columns), 1)
    above = np.where(count[..., None] > 0, total / np.maximum(count[..., None], 1), 0)
    above, _ = grow_paint(above, count > 0, passes=size)
    above = np.asarray(Image.fromarray(np.clip(above, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(3)), float)
    columns, rows = cells(position[crown]).T
    out[crown] = above[rows, columns]
    return out, crown


def paint(args, brief):
    """Repaint a built body whose colour came out blotchy, from flat renders of itself, keeping its shape. Set the result
    as the brief's body_base."""
    from slopforge.backends.comfyui import ComfyUIClient
    build, out = Path(args.body), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    native = build / "native_material/basecolor.png"
    run_blender("character_view.py", model_in(build, "body"), native, out, 1024, *BODY_ANGLES, log=out / "views.log")
    texels = np.load(out / "texels.npz")
    client = ComfyUIClient(os.environ["COMFYUI_URL"])
    workflow = json.loads((ROOT / "workflows/image_edit_qwen_api.json").read_text())
    paintings = paint_views(client, workflow, BODY_ANGLES, BODY_PAINT_PROMPT.format(**brief), args.seed or SEEDS[0], out, body=True)
    colour = Image.open(native).convert("RGB")
    size = colour.size[0]
    small = np.asarray(colour.resize((size // 2, size // 2), Image.LANCZOS))
    painted, changed = project_views(small, texels, json.loads((out / "views.json").read_text()), paintings)
    changed &= ~neck_skin(small, texels)
    blend_in(Image.fromarray(small), painted, changed).resize((size, size), Image.LANCZOS).save(out / "basecolor-body.png")
    print(out / "basecolor-body.png")


def model_in(folder, part):
    """The built model, not the _prepared, _detail or _untextured copies the 3D step leaves beside it."""
    found = sorted(folder.glob(f"*{part}.glb"))
    if len(found) != 1:
        raise SystemExit(f"Expected one {part} model in {folder}, found {[path.name for path in found]}")
    return found[0]


def match_skin(colour, voxel, height, tone, keep=None):
    """Body skin in the repainted face's tone, keeping its light and dark. The generator paints skin a saturated orange wherever
    the concept doesn't reach, and a head edit leaves a paler neck than the face: three skin tones on one man. Skin is found in the
    generator's colour, whose tone is even, by matching the bright warm texels on the neck, below the stump's flat top, which comes
    out a different yellow. `keep` masks what stays as it is, such as metal. Arrays are RGB floats of one size."""
    hsv = np.asarray(Image.fromarray(np.clip(voxel, 0, 255).astype("uint8")).convert("HSV"), float)
    top = height.max()
    neck = (height <= top - 0.015) & (height > top - 0.08) & (hsv[..., 1] > 0.3 * 255) & (hsv[..., 2] > 120)
    if not neck.any():
        return colour
    reference = np.median(hsv[neck], 0)
    if reference[0] > 0.14 * 255:  # not a skin colour, so nothing to anchor on
        return colour
    hue = np.abs(hsv[..., 0] - reference[0])
    hue = np.minimum(hue, 255 - hue) / 255
    weight = (np.clip((0.03 - hue) / 0.012, 0, 1) * np.clip((hsv[..., 2] / reference[2] - 0.4) / 0.15, 0, 1)
              * np.clip((hsv[..., 1] / reference[1] - 0.45) / 0.15, 0, 1))
    # The cut rises to the nape, so the stump's yellower inner wall shows under the chin.
    weight[(height > top - 0.1) & (hsv[..., 1] > 0.3 * 255) & (hsv[..., 2] > 120)] = 1
    if keep is not None:
        weight[keep] = 0
    skin = weight > 0.5
    if not skin.any():
        return colour
    weight = np.asarray(Image.fromarray((weight * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(2)), float)[..., None] / 255
    # Anchored on the neck, which meets the face, and compressed: the concept's pale neck and the mottled hands sit far apart.
    light = colour @ np.array((0.299, 0.587, 0.114))
    anchor = neck & skin
    graded = (np.maximum(light, 1) / np.median(light[anchor if anchor.any() else skin]))[..., None] ** 0.6 * tone
    return np.clip(colour * (1 - weight) + graded * weight, 0, 255)


def face_tone(colour, texels):
    """The repainted face's skin colour: the median of the cheeks and nose, which no cap or hair covers."""
    position, normal, used = texels["position"], texels["normal"], texels["used"]
    z = position[..., 2]
    low, high = z[used].min(), z[used].max()
    x = position[..., 0]
    middle = np.median(x[used])
    cheeks = used & (np.abs(normal[..., 1]) > 0.5) & (position[..., 1] < np.median(position[..., 1][used])) & (np.abs(x - middle) < 0.2 * (high - low)) \
        & (z > low + 0.45 * (high - low)) & (z < low + 0.62 * (high - low))
    return np.median(np.asarray(colour.convert("RGB").resize(used.shape[::-1], Image.BILINEAR), float)[cheeks], 0)


def join(args, brief):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    body_dir, head_dir = Path(args.body), Path(args.head)
    body_glb, head_glb = model_in(body_dir, "body"), model_in(head_dir, "head")
    run_blender("character_facing.py", body_glb, out / "facing.npz")
    colour, metal, roughness = body_maps(body_dir / "native_material", out / "facing.npz", brief.get("grade"), brief.get("body_base"))
    head_colour = Image.open(brief["head_base"])
    size = colour.size[0]
    height = np.asarray(Image.fromarray(np.load(out / "facing.npz")["height"]).resize((size, size), Image.BILINEAR), float)
    voxel = np.asarray(Image.open(body_dir / "native_material/basecolor_voxel.png").convert("RGB"), float)
    brass = np.asarray(metal) > 127
    graded = match_skin(np.asarray(colour, float), voxel, height, face_tone(head_colour, np.load(Path(brief["head_base"]).parent / "texels.npz")), keep=brass)
    colour = Image.fromarray(graded.astype("uint8"))
    black, rough = Image.new("L", head_colour.size, 0), Image.new("L", head_colour.size, 191)
    maps = {"base": out / "sheet_base.png", "metal": out / "sheet_metal.png", "rough": out / "sheet_rough.png", "normal": out / "sheet_normal.png"}
    compose_sheet(colour, head_colour).save(maps["base"])
    compose_sheet(metal, black, "L").save(maps["metal"])
    compose_sheet(roughness, rough, "L", fill=191).save(maps["rough"])
    head_normal = Image.fromarray(flatten_normals(np.asarray(Image.open(head_dir / "native_material/normal.png").convert("RGB")), HEAD_NORMAL))
    compose_sheet(body_normal(body_dir, brief), head_normal, fill=(128, 128, 255)).save(maps["normal"])
    request = {"body": str(body_glb), "head": str(head_glb), "height": brief["height"], "name": brief["name"],
               "maps": {key: str(value) for key, value in maps.items()}, "output": str(out / f"{brief['name']}_joined.glb"),
               "report": str(out / "join.json")}
    if brief.get("body_smooth"):
        request["body_smooth"] = brief["body_smooth"]
    concept_cut = out / "concept-cut.png"
    if not concept_cut.exists():
        subprocess.run([sys.executable, str(ROOT / "processing/prepare_3d_input.py"), "--input", brief["concept"], "--cutout", str(concept_cut),
                        "--output", str(out / "concept-flat.png")], check=True)
    alpha = lambda path: np.asarray(Image.open(path).convert("RGBA"))[..., 3] > 128
    request["collar_share"], request["skull_share"] = head_measures(alpha(concept_cut), alpha(body_dir / "cut-raw.png"))
    head_normal.save(out / "head_normal.png")
    head_colour.convert("RGB").save(out / "head_base.png")
    request["head_maps"] = {"base": str(out / "head_base.png"), "normal": str(out / "head_normal.png")}
    (out / "join_request.json").write_text(json.dumps(request))
    run_blender("join_character_parts.py", out / "join_request.json", log=out / "join.log")
    print((out / "join.json").read_text())


POSES = ("t_pose", "raised_arms", "crouch", "leg_lift", "elbow_bend", "shoulder_rotation")


def rig(args, brief):
    out = Path(args.out)
    (out / "Review").mkdir(parents=True, exist_ok=True)
    rigged = out / f"{brief['name']}_rigged.fbx"
    rigged.unlink(missing_ok=True)
    # Review-only: the neck base keeps a few open edges inside the collar.
    request = {"source": args.joined, "rigged_model": str(rigged), "rigged_blend": str(out / f"{brief['name']}_rigged.blend"),
               "report": str(out / "rig.json"), "topology_policy": "allow_for_review", "long_skirt": bool(brief.get("long_skirt")),
               "solid_only": True, "keep_contacts": bool(brief.get("keep_contacts")),
               "evidence": {pose: str(out / "Review" / f"{pose}.png") for pose in POSES}}
    (out / "rig_request.json").write_text(json.dumps(request))
    run_blender("rigify_character.py", out / "rig_request.json", log=out / "rig.log")
    print(json.loads((out / "rig.json").read_text())["status"], rigged)


def walk(args, brief):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = args.clip or Path(args.motion).stem
    request = {"rig": args.rig, "motion": args.motion, "output_blend": str(out / f"{name}.blend"), "report": str(out / f"{name}.json"),
               "in_place": True, **({"clip": args.clip} if args.clip else {})}
    (out / f"{name}_request.json").write_text(json.dumps(request))
    run_blender("retarget_mocap.py", out / f"{name}_request.json", log=out / f"{name}.log")
    print(out / f"{name}.blend")


def unity(args, brief):
    """The rigged figure in a Unity project as a Humanoid prefab with its material. Refuses a folder that exists, because
    a stale .fbx.meta keeps the previous skeleton: move it aside first."""
    import shutil
    from slopforge.unity_animation import build_animator
    from slopforge.unity_material import build_unity_material, make_metallic_gloss
    root, rig_dir, joined = Path(args.project).resolve(), Path(args.rig), Path(args.joined)
    name = brief["name"]
    out = root / "Assets/Art/Generated/Characters" / name
    materials = out / "Materials"
    if out.exists():
        raise SystemExit(f"{out} already exists; move it and its .meta aside first")
    materials.mkdir(parents=True)
    fbx = out / f"{name}.fbx"
    shutil.copy(rig_dir / f"{name}_rigged.fbx", fbx)
    maps = {key: materials / f"{name}_{key}.png" for key in ("basecolor", "normal", "metallic_gloss", "emission")}
    shutil.copy(joined / "sheet_base.png", maps["basecolor"])
    shutil.copy(joined / "sheet_normal.png", maps["normal"])
    make_metallic_gloss(joined / "sheet_metal.png", joined / "sheet_rough.png", maps["metallic_gloss"])
    Image.new("RGB", (64, 64), (0, 0, 0)).save(maps["emission"])
    material = materials / f"{name}.mat"
    build_unity_material(root, fbx, material, maps, render=joined / "unity-views.png")
    mapping = json.loads((rig_dir / "rig.json").read_text())["unity_humanoid_mapping"]
    print(build_animator(root, name, fbx, [], out, rig_type="humanoid", humanoid_mapping=mapping, material=material))
    from slopforge.unity_gear import open_skin
    open_skin(root, f"Assets/Art/Generated/Characters/{name}/{name}.prefab", f"Assets/Art/Generated/Characters/{name}/Materials/{name}.mat")


def gear(args, brief):
    from slopforge.unity_gear import equip, import_clip_library, narrow_leg_swing
    root = Path(args.project).resolve()
    library = import_clip_library(root, args.clip_library, Path(args.clip_library).parents[1] / "License.txt")
    name = brief["name"]
    if brief.get("leg_swing"):
        narrow_leg_swing(root, f"Assets/Art/Generated/Characters/{name}/{name}.fbx", library.relative_to(root).as_posix(), *brief["leg_swing"],
                         arm_drop=brief.get("arm_drop", 1.0), level_head=True)
    equip(root, f"Assets/Art/Generated/Characters/{name}/{name}.prefab", args.pack, args.weapon, library.relative_to(root).as_posix(),
          pack_scale=args.pack_scale, pack_height=args.pack_height)
    print(f"Assets/Art/Generated/Characters/{name}/{name}_equipped.prefab")


NEEDS = {"images": ("style",), "hair": ("style",), "paint": ("style",), "join": ("concept", "head_base")}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=("images", "build", "hair", "paint", "join", "rig", "walk", "unity", "gear"))
    parser.add_argument("brief")
    parser.add_argument("--out", required=True)
    parser.add_argument("--head-source"), parser.add_argument("--body-source"), parser.add_argument("--takes", type=int, default=6)
    parser.add_argument("--image"), parser.add_argument("--part", choices=("head", "body")), parser.add_argument("--seed", type=int)
    parser.add_argument("--body"), parser.add_argument("--head"), parser.add_argument("--joined")
    parser.add_argument("--rig"), parser.add_argument("--motion"), parser.add_argument("--clip"), parser.add_argument("--project")
    parser.add_argument("--clip-library"), parser.add_argument("--pack"), parser.add_argument("--weapon")
    parser.add_argument("--pack-scale", type=float, default=1.0), parser.add_argument("--pack-height", type=float, default=0.68)
    args = parser.parse_args()
    brief = json.loads(Path(args.brief).read_text())
    missing = [key for key in NEEDS.get(args.step, ()) if not brief.get(key)]
    if missing:
        parser.error(f"{args.step} needs {', '.join(missing)} in the brief: see \"Characters built in parts\" in docs/CHARACTER-RIGGING.md")
    {"images": images, "build": build, "hair": hair, "paint": paint, "join": join, "rig": rig, "walk": walk, "unity": unity, "gear": gear}[args.step](args, brief)


if __name__ == "__main__":
    main()
