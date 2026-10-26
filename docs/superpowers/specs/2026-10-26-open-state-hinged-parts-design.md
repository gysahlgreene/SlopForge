# Hinged parts generated open

## Status and scope

Design, 2026-10-26, for M3's props with parts (the hybrid route, merged in #122). It changes how a hinged part that
opens onto an inside (a chest's lid, a cabinet's door, a hatch) is generated. Weapons' slides and triggers keep the
hybrid route. The evidence is a spike on one chest (private run `OPEN1`, scratch tools). The owner left both
decisions below to the agent ("sure, what ever you think is best", 2026-10-26); they are ruled at the end.

## Problem

On the hybrid route a chest is generated closed and cut apart. Three live runs of the same brief (HC4-HC6, nine
seeds) produced no chest that passed:
- **The inside is invented.** Nothing shows what the inside looks like (the owner, 2026-10-25: "there is no
  reference image of what the inside should look like"). A container's opening becomes a box-shaped cavity of one
  texel's colour; any other opening, a surface spanned between the cut's sides.
- **The cut wanders.** The graph cut follows the creases of planks and iron bands, not the seam (HC6 seed 1: 7.8
  object lengths of cut against ~3.4 for a seam loop). The lid's arched ends stayed with the body on two of three
  HC6 seeds: the visible end's lower third projected below the concept's seam, the hidden end had no mask vote,
  and OmniPart's lid left both out.
- **Closing a wide opening fails.** The interface (the zero set of the distance difference between the pieces)
  is ill-conditioned far from the cut: it crumpled into grey sheets inside the body and under the lid.

## Evidence from the spike (OPEN1, 2026-10-26)

1. Qwen-Image-Edit-2511 (Apache-2.0, already installed for multi-view; its angles LoRA set to 0) edited the
   approved chest concept with an open-lid prompt. All three seeds opened the lid and drew a plain plank inside; seed
   2 kept the lid's iron bands, arched end trims and the hasp.
2. TRELLIS.2 (the H100 final graph, hidden faces removed, 24k faces) on that image built the inside: plank walls
   and floor, the lid's underside, hinges, the hasp. Mesh seed 1 came out in 362 pieces (9,406 enclosed vertices
   removed); seed 2 was one piece with a few specks.
3. SAM 2.1 on the open image with a box around the lid masked the whole lid (score 0.98). Labels from that mask
   alone, with no OmniPart, split seed 2 cleanly: lid 0.42 of the area, a cut of 1.9 object lengths along the
   hinge line only. Open, the lid meets the body only at the hinge, so the minimum cut finds it.
4. Closing the lid: the lid had opened about 56°, not the 100° the prompt asked for. Its flat side was 9% shorter
   than the opening it must cover (seed 1: 13%): from one view TRELLIS.2 foreshortens a lid seen at an angle.
   Features picked off the outline (corners, the contact centroid, support planes) were thrown off by the hinge
   knuckles, the hasp and loose specks. What worked was fitting what matters: starting from each piece's flat open
   face, a search over the turn, an offset and a stretch across the opening minimised the rays from the cavity
   that escape between lid and body, plus lid points inside the walls, plus the `part_open` measure of backs of
   faces seen. Result: turned 59.5°, stretched 1.21, 0.03% of rays escaping, no lid point in the walls, backs of
   faces 0.0097 with the hinge cut still open (the final pass closes it).

## Design

For a part declared as a hinge on an asset type with `open_state: true` (the prop type first):

1. **Open concept** (conditioning, after concept approval): candidates of the approved concept with each such part
   open, from the edit graph (`workflows.edit`, the views graph with its LoRA at 0). The prompt names the part, its
   hinge edge (from the anchor), an opening angle, and the inside from a new optional `--inside "<description>"`
   (default: plain, in the outside's material). The candidates are listed with the concept candidates.
2. **Approval**: `approve <name> <concept> --open <n>` takes the chosen open candidate (decision 1). Its hash and
   the edit prompt join the conditioning stage's identity; a new open candidate regenerates the mesh.
3. **Mesh**: TRELLIS.2 from the open concept's cutout, as today (hidden faces removed; the inside is visible, so it
   stays).
4. **Masks and split**: SAM on the open concept with the part's open-state box (`--part-box`, measured on the
   open concept as boxes are today). Labels from the mask votes and the crease pairwise term only; OmniPart is not
   run. A loose piece takes the label of the nearest labelled face, so specks do not stay with the body.
5. **Close** (final pass, before coverage, anchors and gates): the hinge line from the contact between the pieces
   (its direction snapped to x, y or z); each piece's open face; the face match as the start; the seal search
   (turn, offset, stretch along the opening's depth) as above. The part is left in its closed pose, the rest pose.
6. **Then the existing final pass**: the hinge cut closed by its interface (now a thin strip, not a wide opening),
   the pivot from the declared anchor, the penetration sweep from closed to open, `part_open`, the prefab, the
   Animator and Play mode.

New gates (calibrated on the first live runs, then fixed):
- `part_seal`: rays escaping the closed cavity, retried above a threshold (spike: 0.0003 fitted, 0.0033 unfitted).
- `part_fit`: the stretch, retried outside a range (spike: 1.21; decision 2 sets the range).
- The existing coverage gate measures the closed part against the approved concept's mask, so a closed lid that does
  not look like the concept's still fails.

## Decisions for the owner

1. **Is the open concept a second approval?** Recommended: yes. The edit changes details (the spike's hasp moved,
   one seed dropped the lid's bands), and the finished asset follows the open image, not the closed concept.
   Without an approval the pipeline would pick a seed itself.
2. **May the pipeline stretch a generated part to fit its seat?** Recommended: yes, across the opening's depth
   only, within 0.9-1.3, as a recorded step of the closing fit. A real lid matches its opening, and TRELLIS.2
   foreshortens a lid seen at an angle (9% and 13% on the spike's seeds). The alternative is to retry seeds until one
   fits within a tolerance, which the spike suggests may rarely happen.

## Out of scope

Weapons (a slide drawn back reveals little); several hinged parts on one asset (one lid first); multi-view
conditioning of the open concept; doors in kit modules.

## Verification

Unit: the prompt and identity changes; the split with mask votes only; the snapped hinge line. Opt-in Blender: a
fixture box with a lid generated open at 60° closes sealed with the right turn and stretch; a lid fused to the body
along its hinge edge separates at it; specks take their nearest label. Live: the chest brief through approve,
approve-texture, Unity and Play mode on two independent runs, with closed and open renders sent to the owner.

## Risks

The edit may change the object's design (decision 1 contains this). TRELLIS.2 seeds can fragment (seed 1). The
seal search is a local search from the face match; a face match that is far off (a door opened past 90°, a lid
open both ways) may need a wider start. The hinge cut's interface was built for wide cuts; on a thin strip it may
over-spend the face budget.

## Rulings and implementation (2026-10-26)

1. **The open picture is a second approval.** `slopforge open <name> <concept> [--count N] [--inside TEXT]` makes
   candidates with `open_of: <concept>`; `approve <name> <concept> --open <n>` approves both. The review board
   offers that command on an open picture's card. No `open_state` type flag: the approval chooses the route.
2. **A part may be stretched to fit, by at most 15% either way** (1/1.15 to 1.15), across the opening's depth
   only. The seal search stays within the bound; the face match's own stretch is gated (`part_fit`), so a lid
   clamped short of its opening is retried rather than left with a gap. The spike's lid needed 1.08 to 1.21
   depending on the fit (the published GIF's fit: 1.13); seed 1's 13% foreshortening would need 1.15. If live seeds
   mostly need more, widen the bound with that evidence.

Differences from the design above: the open picture's masks take their own box (`approve --open-part-box`), else
the part's text alone; the closing runs in the mesh stage (`blender/close_part.py`, its hash and the bound in the
stage's identity), so the final pass is unchanged; `part_seal` is reported in `generation.json` (`open_state.close.
seal`), not gated yet. Tests: open candidates and their lineage, the approval guards, conditioning and mesh from
the open picture, the rim rule, the mask-only split, the stretch gate, the CLI and the review board; opt-in
Blender: a thick-walled box with a half-cylinder lid generated open at 70 degrees and 8% short closes sealed
(turn 68-72.5, stretch 1.09-1.13), and one 30% short reports the stretch it needed. Live runs: not yet.
