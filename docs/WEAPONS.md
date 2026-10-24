# Weapons

Weapons are roadmap milestone M3 ([epic #107](https://github.com/gysahlgreene/SlopForge/issues/107)). They are
**Experimental**: the `weapon` asset type exists, but no weapon has yet gone through the protocol. Moving parts,
the grip pivot, a check for thin parts and the bowstring are planned steps, listed in the epic.

## The `weapon` type

[`templates/asset_types/weapon.yaml`](../templates/asset_types/weapon.yaml) differs from a prop in three ways:
- **A side-profile concept on a wide canvas** (1536 × 640). The tip or muzzle points right and the grip sits on the
  left, so a long blade or barrel fills the frame. `--aspect` overrides it for one asset.
- **Its own shape rule.** Props are told "no thin hollow tubes, open rings, wires, or paper-thin parts", because
  image-to-3D drops thin parts. A weapon cannot follow that rule, so its rule asks for:
  - blades, guards, limbs and barrels drawn with their real thickness;
  - a bowstring drawn as one taut line;
  - no loose straps or floating parts.
- **A centred pivot when sized.** `--target-size` sets the pivot from the asset type. Props and structures stand on
  their base; weapons keep a centred origin until the grip pivot lands.

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

**How approval masks the parts:**
- After the concept is cut out, approval masks each part on it.
- [Florence-2 large](https://huggingface.co/florence-community/Florence-2-large) (MIT) detects the part from its
  description, and [SAM 2.1](https://huggingface.co/facebook/sam2.1-hiera-large) (Apache-2.0) cuts its mask inside the
  concept's outline.
- Open-vocabulary detection is used, not phrase grounding: grounding "glass globe" on a lantern also boxed the whole
  lantern.
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

- **Thin parts.** Image-to-3D may still thicken, break or drop thin parts. The concept-fit check fills each row of
  the outline between its outer edges, so it cannot see a missing bowstring. A thin-feature check is planned.
- **Single mesh.** Every weapon is still one mesh. Moving parts are planned: each part split from the one generated
  mesh along a mask drawn on the concept.
