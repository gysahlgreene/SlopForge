# Props lineup (2026-10-22)

![Seven generated props turning on a dark stage](props_lineup.gif)

This is the README's banner image. It shows seven props from runs that passed through Unity import. It is
presentation only and adds no evidence.

| Prop | Run | Evidence |
| --- | --- | --- |
| Stone lantern | Criterion v5, C2 | [Protocol runs](../props-provisional-2026-10-v5/README.md) |
| Glazed jug | Criterion v5, B2 | [Protocol runs](../props-provisional-2026-10-v5/README.md) |
| Mossy tree stump | Coverage, F2 | [New prop kinds](../props-coverage-2026-10/README.md) |
| Supply crate | Criterion v5, A1 | [Protocol runs](../props-provisional-2026-10-v5/README.md) |
| Cast-iron pot | Coverage, D1 | [New prop kinds](../props-coverage-2026-10/README.md) |
| Sci-fi fuel canister | Coverage, E1 | [New prop kinds](../props-coverage-2026-10/README.md) |
| Brass lantern | Coverage, G1 | [New prop kinds](../props-coverage-2026-10/README.md) |

**How it was rendered:**
- Each prop's meshes and materials were appended unchanged from its first material candidate's preview
  `.blend` into one Blender 5.1 EEVEE scene.
- Each prop was scaled to a similar on-screen size, so the sizes are not to scale with each other.
- Each prop turns once about its own axis, starting at a different angle from the others.
- The lighting is a key and a rim spotlight per prop, over a dark floor.
- The frames were assembled with ffmpeg, using one 256-colour palette for every frame and error-diffusion
  dithering. Pillow's median-cut palette lost the moss green, the canister's orange and its cyan to the
  dark floor's greys.

The render script is kept with the run folders, outside Git.
