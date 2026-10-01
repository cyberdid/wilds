---
name: sprite-artist
description: Use when adding, redrawing or animating any sprite in Wilds (tiles, creatures, heroes, NPCs, items, UI icons, effects, locations), when a new game object needs art, or when a gfx sprite-coverage test fails. Explains the text-grid pixel-art DSL, the palette, naming/anchors/animation conventions, how to preview and how to validate against the manifest.
---

# Wilds sprite artist

Every sprite in Wilds is **pixel art written as code** in `src/wilds/gfx/sprites/*.py`:
text grids + a legend of palette colour names. No binary art lives in the repo; PNGs are
exported from code (`wilds-sprites`) and can be overridden (`--sprites DIR`).

## Pipeline

`palette.py` (named colours) → `pixelart.py` (`art()` / `Art`, grid helpers) →
`registry.py` (`register(name, art)`) → `bank.py` (pygame surfaces, scale/flip/tint cache,
PNG overrides) → renderer. `manifest.py` is the **contract**: every name the renderer may
ask for, derived from the game's enums. `tests/gfx/test_sprite_coverage.py` fails until each
required name exists with the right size / frame count.

## Authoring

```python
from ..pixelart import art, mirror, shift, overlay, symmetric, recolor
from ..procgen import Canvas
from ..registry import register

LEGEND = {"s": "suit2", "S": "suit1", "v": "glowcyan"}   # char -> palette name
register("t7.thing.idle", art(FRAME_A, FRAME_B, legend=LEGEND, fps=2, note="what it is"))
```

- `.` is transparent. `k` = `ink` (outline), `K` = `ink2`, `w` = `white` are always available.
- Legend values are **palette names only** (`palette.py`); `"name:alpha"` for translucency
  (glows, smoke, glass). Never invent RGB. Add a ramp to `palette.py` only if truly needed.
- Each grid row is stripped of indentation; all rows equal width; no spaces inside rows.
- Variants: register `name@0`, `name@1`, … (static alternatives picked per tile position).
- Procedural textures: draw on a `Canvas` (`noise_fill`, `speckle`, `rect`, `line`,
  `ellipse`, `gradient_v`, `shade_edges`) and `register(..., art(c.grid(), legend=...))`.
  Seed every RNG; output must be identical on every run.
- Helpers: `mirror` (flip), `symmetric` (author left half), `shift` (bob a frame),
  `overlay`/`erase` (layer grids), `recolor(art, {"suit2": "lira2"})` (palette swap),
  `art(..., outline="ink")` (auto 1px outline around opaque pixels - leave a 1px margin).

## Style rules (keep the whole game coherent)

1. **Tile = 16x16 px**, drawn at integer scale (x3 default). Ground tiles exactly 16x16 and
   seamless with themselves and with sibling variants (same mean brightness, no hard
   features touching the edges).
2. **Actors face RIGHT**, 3/4 side view; the renderer mirrors for left. Feet on the bottom
   row; default anchor = bottom-centre `(w//2, h-1)` = the tile's ground point.
   Taller objects (flora, pods, domes, wreck entrances) rise above their tile the same way.
3. **Outline**: 1px `ink` around actors, items, objects. Ground and wall textures have no
   outline. Never use pure black.
4. **Light from the top-left**: highlight top/left edges, shadow bottom/right. 3-4 tones
   per material from one ramp (`moss0..5`, `suit0..4`); shadows hue-shift toward the
   darker ramp steps, highlights toward the lighter ones. Avoid pillow shading.
5. **Contrast hierarchy**: ground is darker and low-contrast; actors/items are brighter,
   saturated and outlined so they read instantly at 16px. Glow colours (`glowcyan`,
   `glowpink`, `neon_*`) are reserved for light sources, eyes, screens, magic-like tech.
6. **Readable silhouettes** first; details second. Check at x3 and at x1.
7. **Animation**: idle 2 frames @1-2 fps (breathing / blinking), walk 4 frames @8 fps
   (contact, passing, contact, passing), attack 2-3 frames @10 fps, ambient loops
   (water, flames, neon) 2-4 frames @2-6 fps. One-shot effects use `loop=False`.
   Keep the body registered between frames (no sliding): move limbs, bob by 1px.
8. **Names**: `t7.*` Tau-7, `cp.*` city, `ui.*` HUD icons (12x12; log markers 8x8),
   `fx.*` effects. Actors use `<who>.<anim>` (`t7.hound.move`, `cp.npc.fixer.elf.idle`).
   City location themes: `sprawl`, `docks`, `corp`, `station`, `outpost`; shared city
   objects live under `cp.any.*`.

## Preview and validate

```bash
uv run wilds-sprites --module tau7_life --out /tmp/sprites --scale 8   # contact sheets
uv run wilds-sprites --module tau7_life --check                       # manifest gaps
uv run python -m pytest tests/gfx -q
```

Open the `sheet-*.png` files and look at them. For terrain, compose a tiny map with
`wilds.gfx.export.mock_scene(bank, rows, layers)` to check seams and how objects sit.
A sprite is done when: it reads clearly at x3, its palette/outline/lighting match its
neighbours on the sheet, animations loop without popping, and `--check` is clean.

## Overrides (artists, image generators)

`uv run wilds-sprites --strips --out DIR` writes `DIR/png/<name>.png` (all frames side by
side, 1x). Edit any of them (Aseprite, a generator like Retro Diffusion / PixelLab), put
them in a folder and run the game with `--sprites FOLDER`: same-named files replace the
built-in art frame-for-frame.


## Azeroth (Mulgore) art

The Azeroth chapter has its own contract, `wilds.azeroth.manifest` (read the generated
`docs/azeroth/mulgore-art-manifest.md`), and its own sprite modules `az_terrain`,
`az_creatures`, `az_monsters`, `az_people_tauren`, `az_people_other`, `az_structures`,
`az_thunder_bluff`, `az_items`, `az_fx`. Names start with `az.`.

- **Scale is real.** A tile is 16 px = 2 yards, so 1 yard = 8 px. A human-sized body fits one
  tile; tauren are 16x24; a kodo is 32x24 (two tiles long); Thunder Bluff's lodges are
  multi-tile pieces. The manifest sizes are the contract - do not shrink a kodo to fit a tile.
- Same rules as above: palette names only, 1px `ink` outline on actors/objects, light from the
  top-left, actors face right with feet on the bottom row, seeded procedural textures.
- Mulgore look: golden-green rolling prairie, red-brown mesas, tauren hide-and-timber huts,
  totems, bright Horde red banners. Palette ramps `moss`, `dust`, `tent`, `rock`, `bone`, `fire`,
  `water` exist; add a ramp to `palette.py` only if truly needed (say so in your report).
- Preview and check one module: `uv run wilds-sprites --module az_terrain --out /tmp/az --scale 6`
  and `uv run wilds-sprites --module az_terrain --check`. A module is done when `--check` is clean;
  then its name is added to `AZEROTH_DONE` in `gfx/sprites/__init__.py`.
