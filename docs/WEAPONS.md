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
- moving parts split from the mesh, with pivots and a hierarchy in the FBX, and a Unity prefab with a checked
  motion clip per part.

**Still planned** (listed in the epic): the W-v1 protocol, and the owner's decisions it needs. The
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
--part "grip=grip: the leather-wrapped grip" --part "trigger=hinge:x:0..20: the curved trigger inside the guard"
```

- **Kinds:**
  - `grip`: one at most, the weapon's handle;
  - `hinge`: rotates about an axis, with its range in degrees; a hinge may add `@face[-face]` (front, back, left,
    right, top, bottom) to pivot on that edge of its own bounds, e.g. `lid=hinge:x:-100..0@back-bottom`. Without it the
    pivot is the part's contact with the body (a trigger's root) or its box centre when it touches nothing;
  - `slide`: moves along an axis, with its range in metres.
- **Axes:** in the weapon's frame as Unity shows it: x right, y up, z forward along the blade or barrel (a prop:
  z towards its concept's camera). A range's sign is Unity's: a positive turn about x takes +y towards +z, about
  y +z towards +x, about z +x towards +y. So a trigger hanging below its pivot pulls back with `0..20`, and a lid
  hinged on the back edge opens with `-100..0`; a slide's range is signed along its axis (`-0.03..0` draws a
  pistol's slide back). The interpenetration check rejects a part turned the wrong way into its body and names
  the sign that clears it.
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
  concept's outline, from its box. SAM returns three candidate masks; the stage keeps the one that fills the box's
  part of the object without spilling out of the box (fill minus twice the spill, SAM's score breaking ties) and
  records every candidate in `masks.json`. SAM's single best answer for a chest's lid box was the two iron band
  arcs on it, 5% of the chest, and every part-level run after it inherited that lid (2026-10-25); the chosen
  candidate covers the whole lid. The tool's hash is in the stage identity, so a change to it re-masks.
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
- A strip of either side along the cut joins the side around it (a live pistol's body had come out in 12–19
  slivers). Larger pieces stay: a pistol's magazine, an interior plate, had followed the slide out.
- A flat seam (within 5% of its extent) is bisected on its fitted plane, so the cut is one straight line; a small
  curved seam keeps its masked outline. A hinge's mask is widened by 1% of the concept first.
- Each side's opening is closed with flat caps, coloured by the texel nearest the median colour along the cut.
- A slide gets a barrel cylinder under it, a static child of the body, so the slide drawn back shows a barrel.
- The part becomes a child of the body. A slide pivots at its bounding box centre, a hinge at the centre of its cut.
- The FBX carries the hierarchy and each part's kind (`slopforge_part`). Inspection records `parts` and leaves them
  out of the component count.
- A part with fewer than eight faces under its mask is not separated, and the candidate fails as the retryable
  `part_missing`, so the next seed is tried.

A pistol's slide and trigger were split this way on three live runs
([evidence](media/weapon-moving-parts-2026-10/README.md)).

**In Unity** (`slopforge/unity_weapon.py`, at `approve-texture` for a weapon with hinge or slide parts):
- A prefab `<name>.prefab` next to the published FBX: an identity root at the grip over the imported model, with an
  Animator whose controller (`Animations/<name>.controller`) has one state per part.
- One clip per part (`Animations/<name>_<part>.anim`): rest at 0 s, the declared limit at 0.5 s, rest at 1 s. A
  slide moves along its declared axis in the weapon's frame; a hinge turns about it at the part's own pivot.
- **Checks**, by sampling each clip at rest and at its limit:
  - a hinge's pivot drifts no more than 1 mm, and it turns within 0.5° of its limit;
  - a slide travels within 1 mm of its limit along its axis, with no sideways movement;
  - the weapon points along +Z from the root, and the root lies inside its bounds.
  - A failed check fails the publication (`weapon_motion`), which rolls back.
- A strip `Previews/<name>_motion.png` shows the weapon at rest and at each part's limit, and the checks are recorded
  as `weapon_motion` in the validation.

The travel check caught a real fault on its first run: the imported FBX root is scaled 100 under Unity's 0.01 file
scale, so a slide moved 3 m until its travel was taken through the parent's scale.

## Moving parts from part-level generation

A weapon that declares a hinge or slide is generated as **separate parts** by OmniPart (MIT; TRELLIS v1 backbone),
not as one mesh cut along masks: cutting one closed surface gave hollow parts with flat caps and lumpy small
mechanisms, which the owner rejected three times (2026-10-24). The weapon type sets `part_model`: `hybrid` (the
default, [below](#hybrid-parts-trellis2s-surface-split-by-omniparts-parts)) keeps TRELLIS.2's surface and uses
OmniPart's parts to split it; `omnipart` uses OmniPart's parts as they are. Static weapons (no hinge or slide) keep the
profile's model graph. The rest of this section describes OmniPart's run, which both routes share.

**Set-up (once, on the part-mask host):** `scripts/install-omnipart.sh [directory]` builds the environment
(micromamba, Python 3.10, torch 2.4 + cu121, `setuptools<81`) and prints the two keys for `ai/project.yaml`:
`tools.omnipart_python` and `tools.omnipart_checkout`. `tools.parts_host` is required: the tool runs there over SSH
with `SPCONV_ALGO=native ATTN_BACKEND=xformers`, as the part masks do. A missing key stops before mesh inference
(`part_model_preflight`, `configuration`; the part masks have already been made).

**How a run goes** (`processing/part_model.py` on the host, then `blender/prepare_parts.py`, then the usual final
pass):
1. Every object pixel of the concept cutout gets a part id: the declared parts in order, then the body. A body
   speck resting on a slide (body all the way down to the slide's top in its column: a pistol's sights) is the
   slide's, since it moves with it. The body's box therefore spans the whole weapon and overlaps every part's box;
   OmniPart resolves the overlap from the masks. (A rule that moved the body above a slide's line into a separate
   part was tried first: the sights stretched that part over the whole slide and OmniPart grew a second shell.)
2. Before the run, each declared part is measured in cells of that structure (64 across OmniPart's 1.2× square
   crop of the object): a part narrower than 3 cells stops the stage as a brief problem, because no seed gives
   it a shape (the 2026-10-25 rifle's 1.7-cell bolt handle and 2.2-cell trigger failed three seeds each;
   a 3.3-cell pistol trigger passed). Draw a moving part at about 5% of the object's longer side or more,
   or declare a larger moving assembly (a bolt with its carrier).
   OmniPart's sparse structure gives the object's occupied voxels (64³). Each part's 2D mask extent is mapped onto
   that extent (image columns along grid x or y, whichever footprint matches the silhouette best, mirrored or not;
   rows down grid z; the full thickness) and becomes its 3D box. The boxes follow OmniPart's bottom-up part order,
   and the tool stops with a clear error if the two orders differ. OmniPart's own layout model (NVIDIA
   PartField) is never called: its licence is non-commercial.
3. OmniPart's MIT part synthesis fills the boxes and returns one textured mesh per part. The tool renames each
   node after its part and records, per declared hinge or slide, a diagnostic `structure_coverage` (the share of
   its mask's grid cells that hold a sparse-structure voxel; a thin lever barely registers there, so it is not the
   gate). OmniPart crops the object square and reads the mask on its 37×37 feature grid, pairing part k with mask id k, so a part too
   thin to be the majority of any cell (a rifle's trigger) would vanish and every later part would take another
   part's image features; such a part is given the one cell it fills most before the mask is written.
4. `prepare_parts.py` welds and reduces each part to its share of the face budget by surface area (floor 2%), with
   the 90% headroom for moving parts, unwraps every part into **one base-colour atlas** baked from the parts' own
   textures (OmniPart bakes each part at the type's `texture_size`, 4096 for weapons, not its 1024 default; its
   sampler runs the type's `part_steps` and `part_cfg`, 25 and 7.5 by default, and a change regenerates), bakes
   a **metallic atlas** from each part's declared class (a part named by a declared non-metal region, as "grips"
   names "grip", is 0; else 1 when the brief declares metal), and bakes each part's **tangent normals** from a
   full-detail copy kept before its reduction, so the generator's bumps, panels and checkering survive. The bake
   margin equals the packing margin, so one part's metallic does not bleed into its neighbour's islands.
5. The backend writes `generation.json` as the TRELLIS route does (`textured`, four maps: the atlas with its unused
   texels filled by the median colour, the baked normal, a roughness from the brief's finish word, the metallic
   atlas), so the material stage runs unchanged, including metal lightness and concept colour transfer: the
   concept-side view joins the parts into one mesh for the render. Unity imports the maps at their size.
6. The final pass (`prepare_model.py --parts-json`) tags each node's faces by part, joins, orients, scales and
   pivots the weapon as one, welds, marks edges over 30° sharp (hard surfaces shade as facets, not gradients), then
   separates the hinges and slides: a slide pivots at its box centre, a hinge at
   the centroid of its vertices within 1% of the size of the rest of the weapon's surface (its contact), or at its
   box centre when it touches nothing. The hierarchy, FBX and Unity motion stage are the same as for a cut weapon.

**Gate:** a declared hinge or slide whose coverage is below the type's `min_part_coverage` (0.55: on the first live
runs passing parts covered 0.61–0.96 of their masks and rejected ones 0.18–0.38), or that was not generated at all, fails as the retryable `part_missing` and the
next seed is tried. The spike of 2026-10-25 lost a part in one seed of four.

**Identity:** the backend's name and the hashes of `part_model.py` and `prepare_parts.py` are part of the mesh
stage's settings; changing either invalidates the stage like a workflow change.

A reduction can crumple a thin-walled part: the 2026-10-25 chest's sixth seed came out of the collapse decimation
with 0.47 of its body's shared edges between faces pointing opposite ways, Unity shaded it in facets and Blender's
custom normals hid it. Inspection records `folded_edge_share` per mesh and a candidate over the type's
`max_folded_edge_share` (0.1; sound meshes read 0.00–0.02) is the retryable `mesh_folded`.

## Hybrid parts: TRELLIS.2's surface, split by OmniPart's parts

`part_model: hybrid` (the template default for weapons and props) keeps TRELLIS.2's surface, with its detail, and
uses OmniPart only to say where the parts are. The owner rejected OmniPart's own parts on looks (2026-10-25):
OmniPart is TRELLIS v1 retrained for parts, a 64-cell structure (3.4 mm voxels on a pistol) with Gaussian-splat
textures, and no colour or normal work downstream can add detail it never made. A part model on TRELLIS.2 would
need retraining on its latent space, so the two are combined after generation instead:

1. TRELLIS.2 generates the surface as for any asset (the workflow route), and OmniPart generates the parts for the
   same concept and masks (`run_omnipart`; its textures are not used).
2. `blender/hybrid_graph.py` repairs the surface locally into a closed manifold (a cut across one of its
   non-manifold edges leaves an opening with loose ends that no fill can close), then records its face graph (faces
   that share an edge, the edge's length and angle), OmniPart's parts, and per moving part a vote from its concept
   mask: +1 where the concept's fitted view sees the face inside the mask, -1 outside, 0 unseen or within 2% of
   the mask's edge (a mask edge carried through the view lands a few millimetres off the surface's crease; at full
   weight it pulled the cut across a panel in teeth). A flat side-profile concept, one that looks along the
   object's thinnest axis within ~11°, votes through the thickness.
3. `slopforge/part_split.py` aligns OmniPart's parts on the surface (the best of the 24 quarter turns with bounds
   fitted, refined by ICP: TRELLIS.2 lays a pistol along Y, OmniPart along X), measures each face's distance to
   each part, and labels the faces with graph cuts on scipy's maximum flow: a face's vote is how much closer it is
   to a part than to the others (1% of the object's size counts as one unit) plus 3 units for a mask vote; cutting
   between two faces costs the edge's length times exp(-(angle/25°)²), so a boundary runs along the surface's own
   creases (a slide's groove, a lid's seam). Moving parts are cut larger first, a trigger from what the slide leaves.
4. `blender/hybrid_apply.py` writes the surface back as one glTF node per part, and the final pass tags, separates
   and pivots the parts as for OmniPart's. With `close_openings` in the part table, every opening the separation
   leaves, on each part and on the body, is closed (`mesh_cleanup.close_openings`): a planar fill in the opening's
   best-fit plane; a chain whose loose ends are close is bridged first; an opening no fill can close (a rim that
   dips into a pistol's bore) gets a flat cap across its convex outline in the plane most of its rim lies in
   (RANSAC), a little inside its piece and facing out. Fills and caps take one texel, their ring's median colour.
5. Gates: `hybrid_alignment_error` over `max_hybrid_alignment_error` (0.03 of the surface's size) is `part_missing`,
   as are a part's mask coverage and the motion sweep, so a seed whose generators disagree is replaced.

Live (2026-10-25, the H1 pistol and P4's OmniPart parts): alignment 1.4% of the pistol's size, the split in 6 s,
slide 0.98 of its mask with 0.01 outside it, trigger 0.83, every opening closed, the motion sweep 0.000. Not yet
verified: the chest through this route, a run through the whole pipeline on the H100, Unity.

## Props with parts

The same declarations work on a prop: the `prop` type sets `part_model: omnipart`, so a chest that declares
`--part "lid=hinge:x:-100..0@back-bottom: the domed lid"` is generated as a body and a lid, framed from its concept
(front towards the concept's camera, top up; no grip, no full-turn search, no tip check), the lid measured against
its mask, separated with its pivot on its back-bottom edge, and published as a prefab whose `lid` trigger and
`lid_open` bool open it. The anchor names an edge of the part's own bounds, so a lid's hinge is `back-bottom`, the
seam it rests on (`back-top` put a domed lid's pivot at its apex), and the sign follows the axis rule above (a
positive turn sank the lid through the body). Both mistakes were made and caught by the interpenetration check on
the 2026-10-25 live runs (0.27 and 0.17 of the lid's vertices inside). A chest is the first prop proven this way
(see the evidence pages).

## The prefab a game uses

`approve-texture` publishes every weapon, and every asset of a type with `unity_prefab: true` (props too), as a
prefab a game can pick up, drop and animate (`slopforge/unity_weapon.py`):
- an identity root at the grip (held assets) or the asset's origin, the imported model under it;
- a **convex `MeshCollider` per mesh**, so a moving part's collider moves with it, and a **`Rigidbody`** of the type's
  `mass` (weapon 1 kg, prop 5 kg by default; a brief can override per type);
- the type's **layer** (`unity_layer`: "Weapons", "Props") when the project defines it, else a visible warning in the
  report and the prefab stays on Default — SlopForge never edits the project's tag manager;
- **sockets** as named child transforms: `Socket_Grip` at the root and `Socket_Muzzle` at the body's +Z end on held
  assets, and `Socket_<part>` at each moving part's pivot, parented to the part;
- an **Animator** with a `Rest` default state and, per hinge or slide, a trigger `<part>` (one pulse rest → limit →
  rest, 1 s) and a bool `<part>_open` that holds the part at its limit while set (0.25 s blends);
- the W9 checks: each pulse clip sampled at rest and limit (pivot drift ≤ 1 mm, angle ±0.5°, travel ±1 mm), and for
  held assets the tip along +Z and the root inside the bounds;
- an **interpenetration check** through each part's range: the clip is sampled at nine points and the share of the
  part's vertices inside the rest of the model (rays along two of three axes crossing the body an odd number of times)
  must not rise more than 0.02 over its rest value — a lid swinging into its chest or a drawer travelling past its
  housing fails the publication. The report records the colliders, the mass, the sockets with their positions,
  the parameters, the default state and each motion's `penetration` (`validation.measured.weapon_motion`).

The final pass already sweeps each part through its declared range in Blender, before any material is generated:
the share of the part's vertices inside the rest of the model at the worst point of its range, over its share at
rest (a point counts as inside when rays along two of three axes cross a mesh an odd number of times, since
generated meshes have holes). A part over the type's `max_part_penetration` (0.02) is the retryable
`part_penetrates`, so a seed whose lid turns into its chest is replaced before materials and Unity (the C3 chest's
lid read 0.047 in Blender and 0.169 in Unity; both reject it). Unity repeats the check on the published prefab
with the same two-of-three-rays rule; a single ray along x read 0.03–0.08 on pistol triggers and a chest lid that
were clear to the eye and to the Blender sweep (2026-10-25).

The FBX import also generates **lightmap UVs** (`generateSecondaryUV`) for every asset that is not held at a grip:
props and other static assets get a uv2 set for baked lighting; held weapons never, because they move with the
player. LODs are not generated (the mesh budget is the one LOD).

After the prefab, the publication **plays it**: a play-mode test assembly is written into the project
(`Assets/SlopForgeTests/PlayMode`, `slopforge/unity_playmode.py`), run with Unity's test runner and removed again. Each hinge or
slide gets `PartPulses("<part>")`: the Animator's trigger is set, the part must have moved at mid-pulse and be back
at rest within 2 mm and 0.5° after 2 s. `RestsOnTheGround` drops the prefab on a floor plane: after 3 s it must be
above the floor and still. The NUnit results are kept beside the asset (`<name>_playmode.xml`) and summarised in
`validation.measured.play_mode`; a failed test fails the publication with its message. The run launches the editor
binary itself (the `unity` wrapper's `-quit` would end a test run before it starts), so it needs the project's
editor version installed by the Hub, or `UNITY_EDITOR_PATH`.

Not checked yet: LODs.

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
- **Moving parts** (pistol, 2026-10-24 and 2026-10-25):
  - masks project straight through the concept's view, so a part must be separate in that view;
  - generated as parts (OmniPart): one seed in four lost a part in the spike (a retry); a tiny part's texture comes
    out pale; large smooth surfaces are TRELLIS v1 quality;
  - cut from one mesh (the route without `part_model`): the parts are hollow and the caps flat; a strip of the
    slide's underside at the muzzle stays with the frame;
  - the clips are editor-sampled for the checks; Play mode is not run.
