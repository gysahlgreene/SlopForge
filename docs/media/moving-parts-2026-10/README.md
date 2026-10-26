# Moving parts: a pistol and a chest (2026-10-26)

Two assets whose parts move as declared. The pistol is a pipeline publication. The chest is a spike of a route that
is not built yet. Both use the `h100` profile; the private run folders are `private/weapons-parts-2026-10-25/HP13`
and `.../OPEN1` (commit of each run in its `commit.txt`).

## Pistol: slide and trigger (Experimental)

<img src="pistol_moving_parts.gif" width="600" alt="A black pistol with rosewood grips: the trigger pulls back, the slide racks back and returns, the trigger releases">

The brief declares the slide as a slide along the barrel, `-0.03..0`, and the 1911's trigger as a slide, `-0.005..0`.
`approve` and `approve-texture` ran on commit `67043b4` with no manual step. The GIF moves the parts exactly as
declared.

**The route** (`part_model: hybrid`, the weapon and prop default):
- TRELLIS.2 builds the surface, and faces no outside ray reaches are deleted before the reduction.
- OmniPart and the concept's part masks only say where each part is. The surface is labelled along its own creases.
- The labels are cut through the faces along a smoothed boundary, not around the triangles.
- Each part and the body are closed where they were cut apart.

**What passed on this seed:**
- The slide covers 1.00 of its mask and the trigger 0.90.
- No more than 0.005 of either part's vertices go deep into the frame through its range, in Blender. Unity read 0.0
  for both on the published prefab.
- Backs of faces seen from 14 directions: 0.0009 at rest, 0.0023 with the slide back, 0.0011 with the trigger pulled.
- The prefab has a convex collider per mesh, a 1 kg Rigidbody, grip, muzzle and part sockets, and an Animator with a
  trigger and a hold bool per part.
- Play mode passed: each part pulses and returns, and the pistol settles on a floor.

**Repeatability so far:** of the five seeds tried since the seat rule (`c206c36`), four published: HP10's second,
and the first seeds of HP11, HP12 and HP13. HP10's first failed the component budget, a fault fixed since. TRELLIS.2
gives a different mesh for the same seed number from run to run. This is one brief: Experimental.

**Fixed on the way here** (each has a regression test, [weapons guide](../../WEAPONS.md)):
- The stray-face cleanup re-oriented the open surface and turned half a pistol inside out.
- A trigger cut from the frame it was fused to failed the motion check by float noise. A slide entering its seat
  now goes into its housing; hinges still count every point.
- The grips' dark grain stayed metal as grey flecks; coloured non-metals now match by hue.
- Hidden-face removal cut visible patches loose; the hidden faces joining them now stay.
- The slide/frame cut ran in triangle-sized teeth that showed as grey shards when racked; faces are now cut along
  the boundary.

**Known limits:**
- **Travel is in model units.** Weapons have no real-world size, so this pistol is one unit long and its 30 mm
  slide travel is 3% of its length. A real 1911's is about 14%. Since fixed for new runs: a slide now needs
  the model's real size (`--target-size`).
- **Small flakes** remain under the ejection port with the slide back.
- **Grip texture varies by seed:** some seeds carry the concept's checkering, this one is plain wood.
- **The chroma check is unreliable on a black weapon:** its concept's median chroma is near grey.

## Chest: lid on a hinge (spike, not a pipeline route yet)

<img src="chest_lid.gif" width="600" alt="A domed wooden chest with iron bands: the lid opens 100 degrees on its back edge onto a plank interior, then closes">

On the normal route a chest is generated closed and cut apart. No seed passed: its inside is invented, and the cut
wandered along plank grooves. This chest was generated **open** so that its inside comes from a picture:

1. **Open concept.** Qwen-Image-Edit-2511 edited the approved closed concept to open the lid onto a plank interior
   (seed 2 of 3).
2. **Mesh.** TRELLIS.2 built it open, with the interior, from that image.
3. **Split.** SAM masked the open lid. Labels from that mask alone split the lid off along its hinge line, and faces
   above the body's rim went to the lid.
4. **Closing fit.** The lid was turned shut about the line where it touches the body, matching the two pieces' flat
   open faces. A search then sealed the box: turned 58°, stretched 1.13 across its depth, no lid point in the walls.
5. **Finish.** The wood's roughness was raised to 0.7, matte: its 0.37 threw streaky highlights.
6. **The pipeline's final pass** ran with the chest's declarations: lid hinge `x -100..0` anchored `@back-bottom`,
   0.6 m tall.

Steps 1 to 5 are scratch tools for now. The final pass's results:
- the closed lid covers 1.00 of the approved closed concept's lid mask;
- 0.000 of its vertices go deep into the body through the swing;
- backs of faces are 0.004 at rest and 0.0059 open.

It has not been published to Unity.

**Known limits:**
- **The lid was stretched 13% to fit.** From one view TRELLIS.2 makes a tilted lid short front to back.
- **The edit model changes details.** The hasp moved, and one seed dropped the lid's bands.
- **The dome's outside is invented** where the open image cannot see it.
- **One light sliver** shows by the right-hand hinge.

Building this route needs two decisions from the owner: whether the open image is a second approved concept, and
whether a lid may be stretched to fit its opening.
