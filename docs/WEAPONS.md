# Weapons

Weapons are roadmap milestone M3 ([epic #107](https://github.com/gysahlgreene/SlopForge/issues/107)). They are
**Experimental**: no weapon has yet gone through the protocol.

**In place:**
- the `weapon` type;
- part masks;
- orientation and the grip pivot;
- the thin-part measure;
- coloured non-metals.

**Still planned** (listed in the epic): splitting moving parts from the mesh, the bowstring, and Unity motion.

## The `weapon` type

[`templates/asset_types/weapon.yaml`](../templates/asset_types/weapon.yaml) differs from a prop in three ways, and shares its mesh graph:
- **A side-profile concept on a wide canvas** (1536 × 640). The tip or muzzle points right and the grip sits on the
  left, so a long blade or barrel fills the frame. `--aspect` overrides it for one asset.
- **Its own shape rule.** Props are told "no thin hollow tubes, open rings, wires, or paper-thin parts", because
  image-to-3D drops thin parts. A weapon cannot follow that rule, so its rule asks for:
  - blades, guards, limbs and barrels drawn with their real thickness;
  - a bowstring drawn as one taut line;
  - no loose straps or floating parts.
- **Held at the grip, tip forward.** A weapon must declare its grip (`--part "grip=grip: ..."`). The final Blender
  pass then orients it and sets its pivot:
  - It finds the view that best fits the concept, searching the front half of the view sphere in 5° steps.
  - **Its top:**
    - A weapon whose thinnest axis is nearer vertical than horizontal lies flat in its concept, like a crossbow drawn
      from above. That axis is its top.
    - A side-on weapon's top is +Z.
  - **Its length** is its longest axis across the top. It is pointed at the end the concept draws on the right, the
    tip or muzzle, and turned to Blender −Y, which is forward once in Unity.
  - **Why the fitted view only picks the tip's end:**
    - TRELLIS.2 rebuilds a weapon side-on and lengthwise whatever the concept's camera, while Pixal3D keeps the
      concept's pose.
    - A flat blade's outline barely changes with tilt, so tilting by the fit rolled a longsword 30° about its length.
    - A pistol's grip leans its full 3D principal axis 19–25° off the barrel.
  - It puts the origin at the centre of the vertices under the grip mask, seen from the fitted view, widened by 1.5% of
    the concept to absorb the view's coarseness.
  - `--target-size=-,<length>,-` then sizes it along its length.
  - Inspection records the fitted view (`concept_view`: fit, theta, phi).
- **The props' mesh graph.** A graph made for weapons, with a finer sharp-feature remesh, added defects without
  keeping more. Pixal3D on `h100_final` came closest to every concept
  ([graph comparison](media/weapon-graph-2026-10/README.md)).

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

Declare each part that a later step will split from the mesh, as `--part`:

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
Splitting parts from the mesh along these masks is the next step (epic #107).

## Known limits

- **Thin parts.** Image-to-3D may still thicken, break or drop thin parts.
  - The concept-fit check fills each row of the outline between its outer edges, so it cannot see a missing bowstring.
  - Thin-part recall (`concept_thin_recall`) is recorded for every weapon, but no weapon limit is declared yet.
  - On a three-quarter crossbow it read 0.51–0.61 although the string was kept. The fitted view's 5° steps misplace
    parts a few pixels wide.
- **Orientation precision.** A grip or stock below a flat-lying weapon leans the plane fitted through it:
  - about 1° on the test fixture;
  - up to 2° on live crossbows, where the true level is unknown.
- **Single mesh.** Every weapon is still one mesh. Moving parts are planned: each part split from the one generated
  mesh along a mask drawn on the concept.
