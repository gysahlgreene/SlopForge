# What's been explored

Read this before trying an approach, so it isn't tried twice. Each row is one thing tried, what happened, and where that leaves it. **Status** is one of:

- **In use:** the pipeline runs on it.
- **Rejected:** tried and turned down, by the owner or the evidence.
- **Blocked:** works, but a licence or a dependency stops it.
- **Parked:** promising or unfinished, tracked in an issue.
- **Untested:** researched only.

One result is evidence for that asset, not a rule. A rejected row means that attempt failed, so reopen it with new evidence, not a retry. Where the detail isn't public, it's in the ledgers and research reports listed in `private/README.md`. Add a row whenever you finish trying something, including failures: see "Finishing a piece of work" in [AGENTS](../AGENTS.md).

## The bar

The owner judges by eye: "good results that look right". It isn't a style rule, and passing checks doesn't meet it. Results are compared against the props, which the owner rated about 60% of the goal on 2026-10-18 and "pretty strong" on 2026-10-22.

## Shape generators

| Tried | What happened | Status | Evidence |
| --- | --- | --- | --- |
| TRELLIS.2 at 1536 shape, 4096 maps | Strong on hard surfaces. Fine strands, fur and thin parts fail in its raw shape, so more seeds or settings can't help. | In use | [Rabbit](media/creature-rabbit-2026-11/README.md), #181 |
| Pixal3D, single view | Matched weapon concepts less cleanly than TRELLIS.2 with the same reduction. | Rejected for weapons | #116, [weapon pipeline](media/weapon-pipeline-2026-10/README.md) |
| Pixal3D with four generated views | Backs stop copying the front, but generated views invent details and shift colours. | Parked, opt-in | [Multi-view](media/multiview-props-2026-10/README.md), #63, #155 |
| Reducing from the full-detail mesh, not the graph's midpoint | Flat steel stays flat and edges stay sharp. | In use | [Mesh reduction](media/mesh-reduction-2026-10/README.md), #115 |
| A sharp-remesh graph just for weapons | Added defects. | Rejected | #113, [mesh graphs](media/weapon-graph-2026-10/README.md) |
| Direct3D-S2 | Trialled and not adopted. | Rejected | #107 |
| Hunyuan3D 2.x | Its licence excludes the EU, including outputs. | Blocked | #176 |
| DreamCharacter-1, StdGEN++, Anime-Ready | No released code as of 2026-10-20. | Untested | None |

## Materials

| Tried | What happened | Status | Evidence |
| --- | --- | --- | --- |
| Materials declared per region in the brief, with checks for colour, emitters, glass and metal | Six protocol runs on props passed. | In use | [Materials](MATERIALS.md) |
| Hand-fixing one generated asset's emitters | A repair proves nothing about the pipeline. Fix the stage instead. | Rejected | None |
| Dark-texture check | Catches meshes TRELLIS textures black. | In use | [Calibration](media/dark-texture-check-2026-10/README.md) |
| Concept proportions by rewording | No wording made a stump wider than tall, 0 to 2 of 6 seeds. An opt-in depth guide made 12 of 12. | In use, opt-in | [Proportions](media/concept-proportion-2026-10/README.md), #65 |
| Per-texel projection of the concept | First A/B said to test further, not adopt. | Parked | #152 |
| Side-profile concept projected onto both sides of a weapon, 2026-11-14 | Lightning gun's tan-baked walnut and leather read as drawn (hue difference 4.34 to 0.11). A pike fitted at 0.84 got its band painted in the wrong place; a rifle fitted from 25° above smeared wood over its barrels; a thin lever placed differently stayed white. | In use for weapons, gated at fit 0.9 and a level view | [Materials](MATERIALS.md) |
| Weapons rolled flat by orientation, 2026-11-14 | The sabre and wrench were generated with their curve and jaws sideways (25 and 20 cm wide, 11 and 8 cm tall). The fit picks a view 25-35° above and orientation only turned about the vertical, so they stayed rolled; a full-sphere view search fit no better. Fixed by standing a side-drawn weapon on its edge from the concept's silhouette before levelling. | Fixed in the final pass | [Weapons](WEAPONS.md) |
| Backdrop kept inside a closed loop, 2026-11-14 | A lever-action rifle's lever loop came out white: BiRefNet kept the backdrop inside the loop as solid (alpha 254), also on close crops of it, while the trigger guard's loop beside it was cleared. Opaque pixels matching a backdrop fitted over the transparent ones found the loop but also a white gauge dial, so colour alone is unsafe; grown from those pixels inside a declared box, the fill stopped at a shading line in the loop. | Open: not fixed; a concept with the loop clearly open is the next try | round 25 ledger |
| Long thin pole weapon after the roll fix, 2026-11-14 | A 2.4 m pike built flat now stands up, but the reconstruction still has a thick blunt head and its band 20% off; its fit (0.84) is under the side projection's 0.9, so the head keeps its brass colour. | Open: geometry, not orientation | round 25 ledger |
| Normals after the H100 graphs | Shipped normals differ from those the normal map was baked against, by about 10 degrees. | Parked | #156 |
| Projecting every concept emitter blob, not only the largest (several emitters of one colour) | A canopy's 12 lenses got their glow on its roof and a column; booth and chamber frames picked up glow. The bounding-box registration can't place many blobs. Reverted, 2026-11-09. | Rejected until registration improves | [Materials](MATERIALS.md) known limit |
| A perspective camera for the concept-view fit | Offline on one canopy: fit 0.971 against 0.955 orthographic, and the lenses landed on their band, but still half off because the model spaced them differently. | Parked, prototype only | [Materials](MATERIALS.md) known limit |
| Telling a wrong colour shift by offset agreement or lightness ratio | Neither separated the bad cells (iron 0.87 agreement; 18 of 23 cells within 3×). The share of coloured cells did. | Rejected | [Materials](MATERIALS.md) |
| Small emitters (`emissive#..@../small`) for automaton eyes, 2026-11-13 | The fleck filter removed eyes ~6 px across on every concept; with `/small` the hand's eyes glow. The rifleman's eyes were lost by the bake itself on 3 of 3 seeds, and the concept projection is gated at fit 0.90 (0.85-0.88 there; offline it landed below the eye). | In use | [Materials](MATERIALS.md) |

## Kits and scenes

| Tried | What happened | Status | Evidence |
| --- | --- | --- | --- |
| One tiling swatch baked into every module | Flattened the stone's colour. Replaced by keeping each module's colours with the kit's tint matched. | Rejected | [Shared material](media/kit-material-2026-10/README.md), #101 |
| Clean Blender geometry with tiling materials | The owner rejected this hybrid on looks. | Rejected | [Kit look](media/kits-hue-match-2026-10/README.md) |
| An L-shape guide for corners | The corner rebuilt as a solid block. | Rejected | None |
| Kits through the protocol | Passed the criteria, but the owner judged them well below the props. | In use, look not approved | [M2-v3](media/kits-provisional-2026-10-v3/README.md) |
| Moorland scene from one recipe | The owner called a prototype's look "perfect". Rebuilt from a blank project. | In use, as a showcase | [Live run](media/natural-live-2026-10/README.md) |

## Moving parts

| Tried | What happened | Status | Evidence |
| --- | --- | --- | --- |
| Cutting parts from one mesh | Rejected three times: flat cut slabs at travel, hollow parts, lumpy small mechanisms. | Rejected | [Cut parts](media/weapon-moving-parts-2026-10/README.md) |
| OmniPart generating parts | Parts work, but its TRELLIS v1 backbone is 64 cells: "none of it looks good enough". Its output is also non-commercial. | Blocked | [Parts](media/weapon-parts-functional-2026-10/README.md), #134 |
| PartField, HoloPart, PartPacker | Non-commercial or Hunyuan-licensed. PartField is avoided by using our own boxes. | Blocked | None |
| TRELLIS.2 surface split by OmniPart labels and masks | The look held on a pistol, but it runs OmniPart, so #134 applies. | Blocked | [Moving parts](media/moving-parts-2026-10/README.md) |
| Chest closed, cut along its seam | 0 of 3 seeds: the cut wanders, and there's nothing real inside. | Rejected | [Moving parts](media/moving-parts-2026-10/README.md) |
| Chest generated open from an edited open picture | Rated "perfect", one run. Needs no OmniPart. | In use | [Moving parts](media/moving-parts-2026-10/README.md) |
| Break-apart rigid parts from SAM masks on the approved 3/4 concept, 2026-11-13 | Patchy arms and legs on the hand: the orthographic fit of a perspective concept was 0.88, and a forearm hid a leg. Eroding the masks helped but did not fix it. | Rejected | [Unreal delivery](UNREAL.md) |
| Break-apart parts from SAM masks on the model's own orthographic front and back renders, 2026-11-13 | 13 clean parts on the hand and the rifleman (plus its rifle, from several boxes and `over`), joints on the parent seam, verified as Unreal 5.8 static meshes. Needs a type that keeps hidden faces: removal had opened the hand to 22,734 edges. Boxes are drawn by hand per model. | In use | [Unreal delivery](UNREAL.md) |

## Characters

| Tried | What happened | Status | Evidence |
| --- | --- | --- | --- |
| Hand-rolled sine-wave walks | The owner: "dont look like walking at all". Use real motion clips. | Rejected | None |
| Whole figure as one model | Lumpy forms, soft faces, fused fingers: the head gets about 1/7 of the resolution. | Rejected for quality | [Character styles](media/character-styles-2026-10/README.md) |
| A head grafted onto a whole body | Helped only the realistic character. | Rejected | `CURRENT_STATE.md` |
| Kits of third-party bodies and clothes (MakeHuman, Quaternius, VRoid) | The owner: "weird and complicated and outside of the scope". Stay inside the generation pipeline. | Rejected | None |
| Separate head and headless body | The owner: "a FAR better example", accepted as placeholders. Four characters reached Unity. | In use | [Route](CHARACTER-RIGGING.md#characters-built-in-parts) |
| Erasing the neck from the headless body | Built a hollow shell with a void at the collar. Taking off only the head works. | Rejected | [Route](CHARACTER-RIGGING.md#characters-built-in-parts) |
| Repairing a bad neck on the built figure, five ways | All failed. Rewording the image edit fixed most of it. | Rejected | [Route](CHARACTER-RIGGING.md#characters-built-in-parts) |
| Fists as lumps with no finger bones | Measured on the grip, but "the way characters hold weapons looks terrible". | Rejected | #178 |
| Open hand with finger bones | Fingers stayed separate in 3D on 3 of 4 takes, and it closes on any handle. Close-ups "still very rough". | Parked | #178, [evidence](media/character-parts-2026-11/README.md) |
| A hand generated already gripping | Looked more natural as clay. Never tried on a figure. | Untested | #178 |
| ActionForge clips | No API or batch route, so it can't be a pipeline step. Its extras are Quaternius clips. | Rejected | [Route](CHARACTER-RIGGING.md#characters-built-in-parts) |
| Library clips for two-handed attacks | No two-handed swing exists in them, and sword clips throw a heavy man 45 degrees forward. | Rejected | [Route](CHARACTER-RIGGING.md#characters-built-in-parts) |
| Overhead hammer attack | The owner: "i was hoping for a hammer swing from the side". | Rejected | [Route](CHARACTER-RIGGING.md#characters-built-in-parts) |
| How characters move | Everything measured passes, yet the owner calls it "still very rough". The cause isn't known. | Parked | #177 |

## Creatures

| Tried | What happened | Status | Evidence |
| --- | --- | --- | --- |
| AI video to rig (Wan 2.2, video2rig) | The owner preferred it to a computed walk on the wolf, but a front paw snaps. It hasn't passed on a second animal. | In use, wolf only | [Fit](media/creature-fit-d-2026-10/README.md), #128 |
| Frame interpolation, 24 fps Wan, more smoothing | Ruled out. More smoothing made the walk stiffer without calming it. | Rejected | #128 |
| Per-frame foot pinning as the cause of the stutter | Leading hypothesis from reading the code. Nobody has run a refit with pinning off. | Untested | #128 |
| Computed walk, idle and hop | The owner passed the rabbit's idle and hop in Unity, and preferred the video walk on the wolf. | In use | [Rabbit](media/creature-rabbit-2026-11/README.md), #153 |
| AI video for a hop | Six clips refused, for views that disagree. | Rejected | #128 |
| A concept drawn smooth with no strands | Clean shape, but it looks like a vinyl toy. With a fur tile: "this is terrible". | Rejected | #181 |
| Matte creature materials | "Less plastic". Uncommitted, with no verdict on the last build. | Parked | #181 |
| Open models newer than TRELLIS.2, and paid services | From published evidence, none gives realistic fur from one brief without an artist. | Untested | #181 |
| Fur as a separate layer: shells, cards, strands | The research ranks strands first on realism, with shells the cheaper gamble, but none has a tested route on this engine. Not run. Its report has the ranked tests. | Untested | #181 |

## Licences

| Tried | What happened | Status | Evidence |
| --- | --- | --- | --- |
| rembg's default model | Had quietly become RMBG-2.0, which is non-commercial. Replaced by BiRefNet. Check a tool's default model, not just its package licence. | Rejected | [Notices](../THIRD_PARTY_NOTICES.md) |
| Qwen Image 2.1 | Research and evaluation licence, and it doesn't clearly free its outputs. Use Qwen-Image-Edit-2511 and Z-Image Turbo. | Blocked | [Route](CHARACTER-RIGGING.md#characters-built-in-parts) |
| DINOv3 | Its own licence, which allows commercial use with attribution. Accepted. | In use | [Notices](../THIRD_PARTY_NOTICES.md) |
| AGPL video2rig | Run as a separate program, never imported. | In use | #128 |

## Quirks that cost time

- **Finger curves in clips:** they're named `RightHand.Index.1 Stretched`, not HumanTrait's `Right Index 1 Stretched`. Under the second name the Animator ignores them, while the clip's values look right.
- **Clips that need a bake:** root curves left unbaked lost the hips' rise and fall, which read as "extremely weird". See [the route](CHARACTER-RIGGING.md#characters-built-in-parts).
- **Runs aren't repeatable:** TRELLIS.2 varies run to run, and character clip bakes aren't byte-repeatable either. Cause unknown.
- **Checks that measure the wrong thing:** fists on grips, and the numbers in #177, all passed while the result looked wrong. Judge by eye as well.
- **Stand-in materials:** motion shown on a flat grey model made the mesh look worse than it was, and drew the wrong verdict.
- **`docs/superpowers/plans/`:** Git ignores this folder except for listed files, so a new plan needs its own line in `.gitignore`.
