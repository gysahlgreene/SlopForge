# Weapons

Weapons are roadmap milestone M3 ([epic #107](https://github.com/gysahlgreene/SlopForge/issues/107)). They are
**Experimental**: no weapon has yet gone through the protocol.

A pistol, a longsword and a crossbow have been through the full pipeline, one run each; the owner accepted their look
for now (2026-10-24, [evidence](media/weapon-pipeline-2026-10/README.md)).

**In place:**
- the `weapon` type, on TRELLIS.2 with Blender's full-detail reduction on every H100 profile;
- part masks;
- orientation and the grip pivot;
- the thin-part measure;
- coloured non-metals, metal brightened to the concept, and concept colours for small parts;
- moving parts split from the mesh, with pivots and a hierarchy in the FBX.

**Still planned** (listed in the epic): Unity motion clips and their checks, and the W-v1 protocol. The
bowstring feature is deferred: every crossbow so far kept its string.

## The `weapon` type

[`templates/asset_types/weapon.yaml`](../templates/asset_types/weapon.yaml) differs from a prop in four ways:
- **A side-profile concept on a wide canvas** (1536 × 640). The tip or muzzle points right and the grip sits on the
  left, so a long blade or barrel fills the frame. `--aspect` overrides it for one asset.
- **Its own shape rule.** Props are told "no thin hollow tubes, open rings, wires, or paper-thin parts", because
  image-to-3D drops thin parts. A weapon cannot follow that rule, so its rule asks for:
  - blades, guards, limbs and barrels drawn with their real thickness;
  - a bowstring drawn as one taut line;
  - no loose straps or floating parts.
- **Held at the grip, tip forward.** A weapon must declare its grip (`--part "grip=grip: ..."`). The final Blender
  pass then orients it and sets its pivot:
  - It finds the view that best fits the concept in 5° steps. A weapon's search covers the full turn, front-facing
    views first: TRELLIS.2 rebuilt three of four side-profile longswords turned 180°, which only a view from behind
    fits. Its colour checks render from the same view.
  - **Its top:**
    - A weapon whose thinnest axis is nearer vertical than horizontal lies flat in its concept, like a crossbow drawn
      from above. That axis is its top.
    - A side-on weapon's top is +Z.
  - **Its length** is whichever of the two axes across the top passes nearest the grip: a crossbow's bow can spread
    almost as far as its stock is long. It is pointed at the end the concept draws on the right, the tip or muzzle,
    and turned to Blender −Y, which is forward once in Unity.
  - **An unreadable view is retried.** Inspection records how far the length runs along the concept's right
    (`tip_alignment`). Below 0.25 the view looks along the weapon and the tip's end is a guess, so the candidate fails
    as the retryable `weapon_orientation`. A reconstruction of two crossed swords measured 0.0.
  - **Why the fitted view only picks the tip's end:**
    - TRELLIS.2 rebuilds a weapon side-on and lengthwise whatever the concept's camera, while Pixal3D keeps the
      concept's pose.
    - A flat blade's outline barely changes with tilt, so tilting by the fit rolled a longsword 30° about its length.
    - A pistol's grip leans its full 3D principal axis 19–25° off the barrel.
  - It puts the origin at the centre of the vertices under the grip mask, seen from the fitted view, widened by 1.5% of
    the concept to absorb the view's coarseness.
  - `--target-size=-,<length>,-` then sizes it along its length, without the kit walls' turn of the longer side onto
    the declared axis.
  - Inspection records the fitted view (`concept_view`: fit, theta, phi, tip_alignment).
- **TRELLIS.2 on every H100 profile** (`model_workflow: weapon_model`). It reduces the full-detail shape in Blender,
  as props do. A pistol, longsword and crossbow through the whole pipeline matched their concepts' forms more cleanly
  than a Pixal3D graph with the same Blender reduction, which only had the pistol's grips closer
  ([full-pipeline comparison](media/weapon-pipeline-2026-10/README.md)). A graph made for weapons, with a finer
  sharp-feature remesh, had added defects ([first comparison](media/weapon-graph-2026-10/README.md)).

Long weapons suit the default `wide` canvas; pass `--aspect landscape` for weapons around 1.5:1, such as pistols and crossbows, and draw a crossbow from above at three-quarters so its bow and string show ([concept trial](media/weapon-concepts-2026-10/README.md)).

It uses the prop limits the owner accepted, none yet calibrated on weapons:
- five parts at most;
- concept fit at least 0.8;
- the colour hue, saturation and darkening limits.

The face budget `weapon_faces` is 30,000, a placeholder until the owner declares one.

```sh
slopforge --project ~/UnityProjects/MyGame generate weapon longsword "A medieval longsword" \
  --image-prompt "A medieval longsword in flat side profile, lying horizontally, tip pointing right: ..." \
  --material "blade=metal: polished steel" --material "grip=nonmetal: dark brown leather" \
  --target-size=-,1.1,-
```

## Parts

Declare each moving part, and the grip, as `--part`. The final Blender pass splits each hinge or slide from the mesh:

```sh
--part "grip=grip: the leather-wrapped grip" --part "trigger=hinge:x:-20..0: the curved trigger inside the guard"
```

- **Kinds:**
  - `grip`: one at most, the weapon's handle;
  - `hinge`: rotates about an axis, with its range in degrees;
  - `slide`: moves along an axis, with its range in metres.
- **Axes:** in the weapon's frame as Unity shows it: x right, y up, z forward along the blade or barrel.
- **Description:** the text after the second colon names the part as the concept draws it. Without one, the part's
  name stands in.

**Locate each part with a box at approval**, once the concept is chosen, as fractions of the concept's width and
height from the top left:

```sh
slopforge approve pistol 2 --part-box "slide=0.17,0.23,0.93,0.39" --part-box "trigger=0.43,0.47,0.49,0.59" \
  --part-box "grip=0.10,0.41,0.35,0.89"
```

**How approval masks the parts:**
- After the concept is cut out, approval masks each part on it.
- [SAM 2.1](https://huggingface.co/facebook/sam2.1-hiera-large) (Apache-2.0) cuts each part's mask inside the
  concept's outline, from its box.
- A part without a box is found from its description by
  [Florence-2 large](https://huggingface.co/florence-community/Florence-2-large) (MIT) open-vocabulary detection.
- `masks.json` records which method found each part (`box_source`).
- **Detection is unreliable on weapons** (2026-10-24, three weapon concepts):
  - Florence-2 swapped a pistol's slide and grip panel, and boxed the whole sword for its grip, crossguard and blade.
  - Grounding DINO boxed the whole weapon for every part, and OWLv2 found some parts but not the slide or the trigger.
  - Single points missed thin parts.
  - Boxes gave the slide (distinct from the frame in the same black finish), the trigger, the grips, a crossbow trigger
    and a sword pommel cleanly.
  - One diagonal bow limb's box took in the crossbow's barrel too.
  - So give a box for every weapon part. Detection worked on a lantern's globe, wire guard and ring.
- The masks, `masks.json` and a review overlay (`parts_overlay.png`) are outputs of the conditioning stage, under
  `candidates/<type>/<name>/parts_<execution>/`. The declared parts are part of that stage's identity, so changing one
  masks again.
- **Pre-check:** a part not found on the concept (under 0.1% of the object) stops approval before mesh inference, as
  a configuration failure (`part_mask_preflight`). Every mesh would lack it too.

**Setup:** the models run in their own environment, on the GPU host over SSH as SkinTokens does, or locally when
`tools.parts_host` is not set. Install it with `scripts/install-part-masks.sh`, then set:

```yaml
asset_pipeline:
  tools:
    parts_host: <ssh host>                    # omit to run locally
    parts_python: /home/<user>/SlopForgeParts/.venv/bin/python
```

On a lantern concept, the models masked the glass globe, the crossed wire guard and the carrying ring precisely.

**How a part is split** (`blender/mesh_cleanup.py`, `separate_part`, in the final pass after texturing):
- Vertices are welded by position, since the textured GLB splits them along UV seams.
- A face belongs to the part when most of its corners project onto its mask from the concept's fitted view; each face
  then takes the majority of itself and its neighbours for four rounds.
- An island of either side that touches the cut joins the side around it (a live pistol's body had come out in 12–19
  slivers).
- Each side's opening is closed with flat caps, coloured by the texel nearest the median colour along the cut.
- The part becomes a child of the body. A slide pivots at its bounding box centre, a hinge at the centre of its cut.
- The FBX carries the hierarchy and each part's kind (`slopforge_part`). Inspection records `parts` and leaves them
  out of the component count.
- A part with fewer than eight faces under its mask is not separated, and the candidate fails as the retryable
  `part_missing`, so the next seed is tried.

A pistol's slide and trigger were split this way on three live runs
([evidence](media/weapon-moving-parts-2026-10/README.md)).

## Known limits

- **Thin parts.** Image-to-3D may still thicken, break or drop thin parts.
  - The concept-fit check fills each row of the outline between its outer edges, so it cannot see a missing bowstring.
  - Thin-part recall (`concept_thin_recall`) is recorded for every weapon, but no weapon limit is declared yet.
  - On a three-quarter crossbow it read 0.51–0.61 although the string was kept. The fitted view's 5° steps misplace
    parts a few pixels wide.
- **Orientation precision.** A grip or stock below a flat-lying weapon leans the plane fitted through it:
  - about 1° on the test fixture;
  - up to 2° on live crossbows, where the true level is unknown.
- **Small detail and finish** (pistol, 2026-10-24):
  - small mechanisms such as a hammer, safety and slide stop stay soft;
  - grip checkering is lost;
  - a small coloured region such as wooden grips can drift in colour, which the whole-object colour checks miss; the
    weapon type shifts non-metal colours towards the concept's (`concept_colour_transfer`, see Materials);
  - generated steel is glossy where a concept shows it satin.
- **Moving parts** (pistol, 2026-10-24):
  - masks project straight through the concept's view, so a part must be separate in that view;
  - the caps closing a cut are flat, so a hollow slide shows a flat slab where it comes off;
  - a small part can leave too few faces under its mask on some seeds (one in two for a trigger of 0.6% of the
    concept), which costs a retry;
  - the parts reach Unity as child objects with pivots, but there is no prefab, clip or playback check yet.
