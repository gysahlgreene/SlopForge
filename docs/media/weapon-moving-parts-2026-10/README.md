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
   then takes the majority of itself and its neighbours, four times, which removes spikes along the cut.
3. Any island of either side that touches the cut joins the side around it.
4. The seam edges are split, each side's opening is closed with flat caps, and each cap takes one texel of the
   surface beside it: the texel nearest the median colour along the cut.
5. The part becomes a child of the body. A slide pivots at its bounding box centre; a hinge at the centre of its cut.
6. The FBX exports the body and its children, with each part's kind as a custom property. Inspection records
   `parts` (name, kind, faces, parent, pivot) and leaves them out of the component count.

**Two faults found on the way:**
- **Slivers.** The first run's bodies came out in 12–19 pieces: ragged masks left strips of body enclosed by slide
  faces, which survive the majority smoothing. Step 3 above fixed it; all later bodies were one piece.

  ![The body after the first cut, with slivers along the slide line](slivers.jpg)

- **Pale caps.** A cap took one boundary texel, which on this pistol was a pale outlier, so the cuts showed as white
  triangles. Step 4's median choice fixed it.

**Live runs** (commit of each in `private/weapons-pipeline-2026-10-24/M*/commit.txt`):

| Run | Seeds | Result |
| --- | --- | --- |
| M1 (first cut) | 3 | every seed cut both parts, then failed the component budget on slivers |
| M2 (islands fixed) | 2 | seed 1's trigger was too small to separate (`part_missing`, retried); seed 2 passed, body in one piece |
| M3 (caps fixed) | 2 | the same: one retry on a missing trigger, then passed; slide 14,834 faces, trigger 120 |

![The M3 pistol at rest and with the slide back 3 cm and the trigger pulled 20°](rest_and_moved.jpg)

The M3 FBX imports with the slide and trigger as children of the body at the recorded pivots, and the project's
Unity preview imported it.

**Limits:**
- **Masks project straight through** the concept's view, so a part must be separate in that view. The frame under
  the slide is only kept because it shows below the slide line; a part hidden behind another cannot be cut.
- **Caps are flat.** Where the slide comes off, the frame's top is a flat slab and the slide is hollow, since the
  generator made one closed surface. At rest nothing shows; at full travel the frame's cap shows at the muzzle.
- **A small part can fail to separate.** The trigger is 0.6% of the concept, and one seed in two left too few faces
  under its mask. The pipeline retries the next seed (`part_missing`).
- **One concept, one weapon.** Three runs of the same pistol concept; no other weapon with moving parts yet.
- **Not checked:** motion in Unity. The parts reach it as child objects with pivots, but there is no prefab, no clip
  and no playback check yet (step W9).
