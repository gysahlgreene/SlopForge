# 2D tileset packs

`slopforge init` installs `starter_tileset_pack` for terrain, paths, water, cliffs, transitions, vegetation, buildings, and decorations. Run it through the standard recipe and review flow. If you have populated an ordered environment/style reference library, pass it to keep the pack aligned:

```sh
slopforge --project ~/UnityProjects/MyGame recipe run starter_tileset_pack \
  --name lunar_outpost --quality-tier draft --reference-library environment/lunar-refinery
```

The selected workflow must return a correctly ordered tile sheet. Approve a child sheet before slicing it. Configure the grid, pixel tile size, margin, padding, layout, collider metadata, and optional four-edge transition masks explicitly:

```sh
slopforge --project ~/UnityProjects/MyGame tilepack lunar_outpost_terrain \
  --grid 4 4 --tile-size 256 256 --pixels-per-unit 256 --layout orthogonal \
  --transition-mask 0 --transition-mask 1 --transition-mask 2 --transition-mask 3 \
  --transition-mask 4 --transition-mask 5 --transition-mask 6 --transition-mask 7 \
  --transition-mask 8 --transition-mask 9 --transition-mask 10 --transition-mask 11 \
  --transition-mask 12 --transition-mask 13 --transition-mask 14 --transition-mask 15
```

Masks use bit values N=1, E=2, S=4, W=8. The command writes row-major RGBA tile PNGs, a normalized atlas, and JSON containing dimensions, layout, collider choice, alpha coverage, per-edge alpha counts, neighbor edge-difference measurements, and optional transition-mask-to-tile mappings. Edge measurements are review diagnostics; terrain transitions can intentionally differ, so they are not treated as universal seam failures. Both orthogonal and isometric layouts use the same deterministic slicing; isometric art should be drawn inside equal-sized square cells.

Add `--unity-assets` when Unity is installed to create native `UnityEngine.Tilemaps.Tile` assets with Sprite import settings and the selected collider type:

```sh
slopforge --project ~/UnityProjects/MyGame tilepack lunar_outpost_terrain \
  --grid 4 4 --tile-size 256 256 --pixels-per-unit 256 \
  --layout isometric --collider grid --unity-assets
```

The generated `Tile` assets can be assigned to Unity Tilemaps. RuleTile and Tile Palette authoring are not generated; transition masks remain inspectable JSON for RuleTile setup or project-specific tooling. Generated PNGs and metadata work without Unity. All outputs are typed artifacts derived from the approved source sheet.

Tile slicing is saved to the manifest before the optional Editor step. If Unity is unavailable during slicing, run `slopforge --project <project> tile-unity <asset-name>` later to create Tile assets from the already packaged images.
