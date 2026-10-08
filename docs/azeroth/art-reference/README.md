# Mulgore pixel art references

`mulgore-grass-imagegen-concept.png` is an ImageGen study for the prairie palette. It is
kept as a visual reference; the runtime grass is the deterministic pixel-grid art in
`src/wilds/gfx/sprites/az_terrain.py`.

The current atlas has 93 terrain tiles and transitions plus 26 original NPC, creature,
and object archetypes in `az_atlas.py`. Their sprite sheet and map views below are
rendered from the same assets used by the viewer. Source spawn records keep their exact
MaNGOS coordinates; archetype art is a pixel-art reconstruction, not a copy of the
original client models.

- `mulgore-overview-final.png` shows the full zone at fit scale with spawn counts.
- `mulgore-detail-final.png` shows a selected Camp Pavilion spawn at 16 pixels per tile,
  the authored sprite art's native scale. There is no player sprite in this atlas.
- `mulgore-atlas-sprites-final.png` and the six `mulgore-terrain-*-final.png` files are
  exported sprite sheets from the live registry.
- The unversioned and `-v2` grass previews are historical early iterations.

Regenerate sprite sheets with:

```bash
uv run wilds-sprites --module az_atlas --out /tmp/mulgore-atlas-preview --scale 6 --prefix az.atlas
uv run wilds-sprites --module az_terrain --out /tmp/mulgore-terrain-preview --scale 6 --prefix az.
```
