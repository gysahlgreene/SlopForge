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

## Known limits

- **Thin parts.** Image-to-3D may still thicken, break or drop thin parts. The concept-fit check fills each row of
  the outline between its outer edges, so it cannot see a missing bowstring. A thin-feature check is planned.
- **Single mesh.** Every weapon is still one mesh. Moving parts are planned: each part split from the one generated
  mesh along a mask drawn on the concept.
