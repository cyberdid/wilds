# Art brief: Mulgore sprites

You draw pixel art **as code** for the Azeroth chapter of Wilds (repo root `/home/user/wilds`). One sprite
module = one file `src/wilds/gfx/sprites/az_<module>.py`. You own exactly that file.

## Read first
1. `.claude/skills/sprite-artist/SKILL.md` (DSL, palette rules, style rules, the Azeroth section at the end).
2. Your module's table in `docs/azeroth/mulgore-art-manifest.md`: every name, size, frame count and
   variant count you must define. This is a contract; `wilds-sprites --check` enforces it.
3. One finished module for style: `src/wilds/gfx/sprites/tau7_life.py` (actors), `tau7_terrain.py`
   (ground), `items.py` (icons), `fx.py`. Read `src/wilds/gfx/palette.py` for the colour ramps and
   `pixelart.py` / `procgen.py` for the helpers.
4. Facts about what you draw: `data/azeroth/mulgore/{npcs,mobs,objects,subzones,lores}.json`
   (records have `title`, `info`, `sections` of plain-text description). Search them with grep/python
   for your subjects and draw what the wiki text says (colours, clothing, weapons, posture).

## The world's scale is real
A tile is 16 px = 2 yards, so 1 yard = 8 px. Sizes in the manifest follow from that (a tauren is
16x24, a kodo 32x24, Thunder Bluff lodges are multi-tile). Never shrink something to fit a tile.
Mulgore's look: golden-green rolling prairie, red-brown mesas and cliffs, tauren hide-and-timber
huts, totems, Horde red banners, warm daylight. Friendly, earthy, readable.

## Visual reference (optional)
You may download a picture from the public wiki to look at proportions and colours, e.g.
`curl -sL -A "wilds-art/0.1" -o /tmp/ref.jpg "https://warcraft.wiki.gg/images/<File name>"` and view it
with the Read tool. Find file names with
`https://warcraft.wiki.gg/api.php?action=query&list=allimages&aiprefix=<Prefix>&aiprop=url|size&format=json`.
Use it only as reference: redraw from scratch in our palette and pixel grid. Do not trace or convert
the image, and do not commit downloaded images.

## How to work
- Draw with text grids + legends of **palette names** (never raw RGB). Procedural textures use
  `Canvas` with seeded RNG; output must be identical on every run.
- If you truly need new colours, add them inside YOUR module by calling `_ramp(prefix, *hexes)` /
  `_named(**colors)` imported from `..palette`, with a prefix unique to your module (`azt_` terrain,
  `azc_` creatures, `azm_` monsters, `azp_` tauren people, `azo_` other people, `azs_` structures,
  `azb_` Thunder Bluff, `azi_` items, `azf_` fx). Do not edit `palette.py` or any other file.
- Reuse heavily: recolour a base body into outfits/species with `recolor`, mirror/shift for animation
  frames, `symmetric` for symmetric art. Keep the body registered between frames (no sliding).
- **Look at your work.** Render sheets and open the PNGs with the Read tool, fix what looks wrong,
  repeat:
  `uv run wilds-sprites --module az_<module> --out /tmp/az_<module> --scale 6`
  (writes `sheet-*.png`). For ground/edge tiles compose a tiny map with
  `wilds.gfx.export.mock_scene` to check seams.
- Done means: `uv run wilds-sprites --module az_<module> --check` prints `0 problems`, every sprite
  reads clearly at x3 and at x1, animations loop without popping, style matches the existing Wilds art.
- Run `uv run --with pyflakes python -m pyflakes src/wilds/gfx/sprites/az_<module>.py` until clean.
- Other agents are writing the other `az_*` modules at the same time: do NOT run the whole test suite,
  do not edit other files, do not commit, do not push. Use only your own `--module` commands.

## Report (your final message, short)
What you finished (counts), anything you could not do and why, any new colours you added, and one
sentence on the weakest part of your art so it can be redone.
