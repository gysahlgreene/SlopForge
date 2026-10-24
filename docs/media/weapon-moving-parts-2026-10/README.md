# Moving parts split from one generated weapon (2026-10-24)

Step W8 of M3 ([epic #107](https://github.com/gysahlgreene/SlopForge/issues/107)). A pistol's slide and trigger were
cut from its one generated mesh along the masks drawn on its concept, closed, parented to the body, and given
pivots by their kind. Nothing was modelled or repaired by hand.

![The pistol's slide travelling back and its trigger pulling, then returning](pistol_motion.gif)

**Brief:** the pistol of the [full-pipeline run](../weapon-pipeline-2026-10/README.md), with two moving parts declared:

```sh
--part "grip=grip: the walnut grip panels" --part "slide=slide:z:-0.03..0: the slide on top of the frame" \
--part "trigger=hinge:x:-20..0: the curved trigger inside the guard"
```

At approval each part was given a box on the concept. SAM 2.1 masked the slide (47% of the object), the grips
(25%) and the trigger (0.6%):

![The concept with the slide, grip and trigger masks tinted](masks.jpg)

**How the cut works** (`blender/mesh_cleanup.py`, `separate_part`), in the final Blender pass after texturing, because
the single-view Pixal3D graph has no prepare step between shape and texture:
1. Vertices are welded by position: the textured GLB splits them along UV seams, and every seam would read as a cut.
2. A face belongs to the part when most of its corners project onto the mask from the concept's fitted view. Each face
   then takes the majority of itself and its neighbours, four times, which removes spikes along the cut. A hinge's
   mask is first widened by 1% of the concept, since SAM masked a trigger's blade alone.
3. Any strip of either side that lies along the cut joins the side around it.
4. Where the seam is flat (within 5% of its extent), the surface is bisected on the fitted plane and the faces near
   the seam take the side of the plane they lie on, so the cut is one straight line. A small curved seam, like a
   trigger's, keeps its masked outline.
5. The seam edges are split, each side's opening is closed with flat caps, and each cap takes one texel of the
   surface beside it: the texel nearest the median colour along the cut.
6. Under a slide, a barrel cylinder is added as a static child of the body, so the slide drawn back shows a barrel.
7. The part becomes a child of the body. A slide pivots at its bounding box centre; a hinge at the centre of its cut.
8. The FBX exports the body and its children, with each part's kind as a custom property. Inspection records
   `parts` (name, kind, faces, parent, pivot) and leaves them out of the component count.

**Two faults found on the way:**
- **Slivers.** The first run's bodies came out in 12–19 pieces: ragged masks left strips of body enclosed by slide
  faces, which survive the majority smoothing. Step 3 above fixed it; all later bodies were one piece.

  ![The body after the first cut, with slivers along the slide line](slivers.jpg)

- **Pale caps.** A cap took one boundary texel, which on this pistol was a pale outlier, so the cuts showed as white
  triangles. Step 5's median choice fixed it.

**The owner's review** of the first result ("not good enough yet") named three faults: flat slabs appearing at full
travel, a lumpy slide rear and hammer, and a trigger that barely read. The second pass (M4, cut offline from M3's
mesh and maps) addressed the first and third:
- **Straight cut and a barrel** (steps 4 and 6). The frame's top is now one flat line, and a barrel shows when the
  slide goes back instead of the frame's cut face. The magazine, an interior plate joined to the body only through
  inner surfaces, had followed the slide out of the grip; only strips along the cut flip sides now, and it stays
  inside the body as its own piece.
- **A whole trigger** (step 2's widening): 288 faces against 120, and a visible pull.
- **Not fixed:** a thin strip of the slide's underside at the muzzle stays with the frame, so a small slab shows
  under the barrel at full travel; labelling in-plane faces by their direction opened the cut and was reverted. The
  slide's rear and hammer are the generator's small-detail limit.
- **A fault of my own along the way:** cutting offline, I passed the candidate's base colour map as the final pass's
  `--surface-source`, which bakes that swatch over the base colour path, and overwrote M3's maps. They were restored
  from the published copies, and the pass now refuses a surface source that is the map it bakes into.

**Live runs** (commit of each in `private/weapons-pipeline-2026-10-24/M*/commit.txt`):

| Run | Seeds | Result |
| --- | --- | --- |
| M1 (first cut) | 3 | every seed cut both parts, then failed the component budget on slivers |
| M2 (islands fixed) | 2 | seed 1's trigger was too small to separate (`part_missing`, retried); seed 2 passed, body in one piece |
| M3 (caps fixed) | 2 | the same: one retry on a missing trigger, then passed; slide 14,834 faces, trigger 120 |

![The M4 cut at rest and with the slide back 3 cm and the trigger pulled 20°](rest_and_moved.jpg)

## In Unity

Publishing the M3 pistol (`approve-texture`) built its prefab, an animator with one state per part, and one clip per
part, then sampled each clip at rest and at its limit:

| Part | Declared | Measured | Pivot drift |
| --- | --- | --- | --- |
| slide | −0.03 m along z | −0.0300 m | 0 |
| trigger | −20° about x | −20.00° | 0 |

The weapon points along +Z from the root, and the root (the grip) lies inside its bounds.

![Unity: the pistol at rest, with the slide back, and with the trigger pulled](unity_motion.jpg)

The travel check caught a real fault on its first run: Unity imports the FBX root scaled by 100 under its 0.01 file
scale, so a slide clip written in the part's local space moved it 3 m. The travel now goes through the parent's
scale. An opt-in test (`tests/test_unity_weapon.py`) builds a slab with a slide and a hinged lever in Blender,
exports it as the final pass does, and checks the same numbers in Unity.

**Limits:**
- **Masks project straight through** the concept's view, so a part must be separate in that view. The frame under
  the slide is only kept because it shows below the slide line; a part hidden behind another cannot be cut.
- **Caps are flat and the parts hollow,** since the generator made one closed surface. The barrel hides most of the
  frame's cap at full travel; a strip of the slide's underside still shows under it at the muzzle.
- **A small part can fail to separate.** The trigger is 0.6% of the concept, and one seed in two left too few faces
  under its mask. The pipeline retries the next seed (`part_missing`).
- **One concept, one weapon.** Three runs of the same pistol concept; no other weapon with moving parts yet.
- **Editor sampling only.** The clips are sampled in the editor for the checks and the strip; Play mode is not run.
