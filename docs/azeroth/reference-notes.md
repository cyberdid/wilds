# Mulgore: what it really looks like (reference notes)

Visual survey of World of Warcraft's Mulgore (Classic + Cataclysm screenshots from warcraft.wiki.gg, CC BY-SA)
against our current look (`shots/new_prairie.png`, `new_BloodhoofVillage.png`, `new_CampNarache.png`,
`new_StonebullLake.png`, `new_ThunderBluff.png`), the recipes in `src/wilds/azeroth/settlements.py`, the flora
scatter in `src/wilds/gfx/az_app.py` (`_scatter`) and the sprite contract in `docs/azeroth/mulgore-art-manifest.md`.
The reference images were looked at only; none are in the repo (file names below are wiki `File:` names).

Scale used throughout: 1 tile = 16 px = 2 yd, a tauren is about 3 yd (24 px). Sizes in yards are estimates
read off screenshots against tauren / kodo for scale, good to roughly +-30 %.

## 0. The one-paragraph brief

Mulgore is a **calm, open, sunlit pasture in a bowl of pale mountains**. Long smooth rolling hills of warm
yellow-green grass with golden swathes; tall golden grass tufts are the main ground texture. Trees are
**only tall pines**, standing alone or in clumps of 2-6, with big gaps (tens of yards) of open grass between.
Narrow pale gravel trails wander between a handful of **small, airy tauren camps**: a few very large white
stitched hide tents, very tall teal-and-red hexagon totems, a campfire, bare tan dirt around the centre, and
nothing else. One horseshoe lake (Stonebull) of pale turquoise water with a soft sandy shore. Herds of kodo,
plainstriders and prairie wolves graze in the open. The mountain ring is **pale beige-grey, rounded and
vertically streaked**, not red. Red/orange rock only appears at Red Rocks and on the Barrens side of the
Great Gate. Thunder Bluff is the only "city" and sits up on its mesas; everything at ground level is
countryside.

Global numbers to aim for:

| thing | real Mulgore | ours now |
|---|---|---|
| trees on open plain | one pine clump (2-6) per ~60-100 yd; lone pines between; about 1 tree per 400-800 tiles overall | groves at 1 tree / 26 tiles where noise > 0.58, plus broadleaf trees; about 1 per 50 tiles in `new_prairie.png` |
| broadleaf trees | none | `az.plant.tree` (acacia/oak) everywhere |
| pine height | 15-25 yd, crown 5-7 yd wide, trunk visible for the lower quarter to third | `az.tb.pine` 24x42..56 px = 3x5..7 yd, trunk hidden |
| ground props | mostly clean grass; golden tufts; flowers rare | about 13 % of grass tiles carry a clump/flower/stone/bush sprite |
| trail width | 2-3 yd (1-1.5 tiles), pale grey-beige gravel with soft tan edges | 3x3 brush plus wobble: 3-5 tiles of red-brown dirt |
| camp footprint | small camp 25-40 yd, village about 150x120 yd | Sungraze r=24 tiles (96 yd across), Narache r=28 |
| building count | small camp 3-5 structures, Bloodhoof 8-10 | Bloodhoof recipe = 69 objects, Narache = 34, Sungraze = 17 |
| water | pale teal-turquoise, see-through near shore, 2-4 yd tan sand/mud band, banks barely sloped | deep navy with bright noise, sunk in a pit with stepped cliff banks |
| mountain rock | pale tan-grey, rounded domes, vertical streaks, moss ledges | `az.mesa.face`/`az.ground.mesa` orange-red; minimap ring brown |

Colour targets (palette guidance, not exact): grass lime-gold `#A8B840` / `#8FA535`, golden swathe `#C4BE55`,
slope shade `#6E8A2E`; trail gravel `#A9A08E` with tan edge `#B89A68`; lake shallow `#6FB5AE`, deep `#3E8590`;
shore sand `#B79A6A`; mountain rock `#C9B9A0` lit / `#8E8172` shade; tent canvas off-white `#E9E1CC` with
brown stitching; totem teal `#4FB8B0` inside dark red `#9A2A22` hex outlines on weathered wood `#8A6A48`.

---

## 1. The open countryside (most of the zone)

### Golden Plains (around Thunder Bluff, SE side) and Rolling Plains (south, toward the gate)
Refs: `Golden_Plains.jpg`, `Mulgore_Wildlife.jpg`, `Rolling_Plains.jpg`, `Red_Cloud_Mesa.jpg`, `Fargaze_Mesa_2.jpg`.

1. What is there: a wide basin of long, smooth hills (crest-to-crest 60-150 yd, height difference 5-15 yd).
   Grass is warm yellow-green with large golden patches; knee-high golden straw tufts are dense in the
   foreground and read as a soft streaky texture. Pines: single tall pines and clumps of 2-6, 3-6 yd apart
   inside a clump, clumps 60-100+ yd apart; the Golden Plains proper are the emptiest part. Kodo herds of 3-6
   grazing, plainstriders in twos and threes, prairie wolves alone or in pairs, small critters (prairie dogs,
   rabbits). A few pale grey boulders/rock mounds near the mountain foot. No shrubs to speak of, no flowers
   beyond faint yellow speckles.
2. Key traits: (a) open space dominates, (b) warm lime-gold colour with smooth large-scale light/shade from
   the hills, (c) tall dark-olive pines as vertical accents only, (d) big grazing animals visible from far,
   (e) pale mountain wall on every horizon.
3. Fixes:
   - `az_app._scatter`: remove `az.plant.tree` on Mulgore grass entirely; pine groves only where noise > 0.75
     and at 1/12 inside that (tight clumps), lone pines at 1/600; no dead trees on the plains (only in
     quilboar land and as rare tall dead pine snags on ridges, see Windfury Ridge).
   - Cut `wildflowers` to about 1/300, `bush` to 1/400, `deco.*` to 1/250; keep `grass_clump` (golden
     variants @2/@3 mostly) at about 1/20 as the main texture.
   - `az.ground.grass`/`tall_grass`: lower the dither contrast to 2-3 neighbouring tones and shift hue warmer;
     add large golden swathes from low-frequency noise instead of tile-level speckle.
   - `az.ground.dry_grass` should be golden straw, not olive-brown.
   - Spawn kodo in herds of 3-6 in the Golden Plains.

### Trails
Refs: `Stonebull_Lake.jpg` (top-down: thin pale line), `Mulgore.jpg`, `Rolling_Plains.jpg`.

1. Narrow (2-3 yd) light grey-beige gravel strips with a soft tan dirt fringe, smooth curves following the
   hills. At camps they widen into a tan dirt patch. Short low wooden rail fences only at bridges.
2. Traits: thin, pale, gently curving; grass right up to the edge.
3. Fixes: `world._wobbly` brush `(0,1,2)x(0,1,2)` -> 1 tile core plus a 50 % feathered edge; lower the
   wobble amplitude from 14 to about 6 tiles; recolour `az.ground.road` to pale gravel.

### Stonebull Lake (and the "Wellspring" question)
Refs: `Stonebull_Lake.jpg`, `BloodhoofVillageStonebullLake.jpg`, `Fargaze_Mesa_2.jpg`, `WorldMap-Mulgore.jpg`.

Note: **Wellspring Lake and Wellspring River are Teldrassil (Shadowglen) names, not Mulgore.** Mulgore's
only large water is Stonebull Lake. After the Cataclysm there is also a small lake in the south of the
Thornsnarl. Nothing called Wellspring should be placed in Mulgore.

1. A long horseshoe lake wrapping Bloodhoof Village on three sides; roughly 350 yd end to end, arms 40-100
   yd wide. Water is pale teal-turquoise, calm, with the lakebed visible near the shore. The shore is a
   continuous 2-4 yd band of tan sand/mud, then grass; banks barely rise (0.5-2 yd). A few pines and fallen
   logs on the banks, sparse reeds. A wooden rope/plank bridge with two carved totem posts at each end
   crosses the narrow northern neck where the Thunder Bluff road crosses. The Ravaged Caravan sits on a
   mound on the NE shore.
2. Traits: (a) light turquoise water, (b) soft sand rim, (c) flat banks, (d) the bridge, (e) village on the
   peninsula.
3. Fixes: relief must put lake shores at water level (no terrace cliffs; `new_StonebullLake.png` shows the
   lake sunk 1-2 steps below the land with black-outlined `dry_grass` walls); add a SAND shore terrain band
   2 tiles wide; recolour `az.ground.water`/`shallows` lighter and calmer (fewer bright noise pixels); add a
   `az.obj.rope_bridge` (or reuse `az.tb.bridge` tiles) at the neck plus two `totem_pole` bridgeheads.

### Red Cloud Mesa (southern plateau, home of Camp Narache)
Refs: `Red_Cloud_Mesa.jpg`, `Red_Cloud_Mesa_Cata.jpg`, `Camp_Narache.jpg`.

1. Not a red rock table: a raised **grassy plateau** of rolling hills ringed by pale grey cliffs, the same
   pastoral grass and pines as below. The south and east parts are scarred by the Bristleback quilboar: dark
   trampled soil, giant curling thorn vines, dead pine snags.
2. Traits: grass on top, cliff rim at the edges, quilboar blight creeping in from the south.
3. Fixes: render Red Cloud Mesa as a GRASS plateau (normal flora rules), cliffs only at the rim; do not use
   `az.ground.mesa`/`_scatter_mesa` (spires, slabs, thornbush) for it. Blight only around Thornsnarl /
   Battleboar Pen / Brambleblade.

### Fargaze Mesa (west of Red Cloud Mesa)
Ref: `Fargaze_Mesa.jpg`, `Fargaze_Mesa_2.jpg` (view from the top over the Bloodhoof valley).

1. Tall mesa with a flat olive-grass top. On top: a sacred ring about 12-14 yd across drawn on bare dirt with
   small orange stones (several concentric circles and a pattern inside), small offering bowls and pots, five
   short carved wooden idol posts (1.5 yd) around it, and three tall winged totems (8-10 yd, teal hex bands,
   plank wing arms, hanging painted hide plaques) behind. A spiritwalker sits in the ring.
2. Traits: open grass top, ring of small stones on the ground (not standing stones), three winged totems.
3. Fixes: add a recipe (no coords in our data; estimate x 40, y 77, verify on the map): `az.obj.offering_ring`
   (new, flat ground decal 96x64), 3 x tall winged totem, 5 x `az.obj.idol_post` (new 16x16), no tents.
   Our `az.obj.stone_circle` (grey Stonehenge slabs) is the wrong idea everywhere in Mulgore.

### Red Rocks (NE)
Ref: `Red_Rocks.jpg`.

1. A cluster of **rounded pale pink-tan sandstone domes and mushroom-shaped hoodoos** (5-20 yd tall) with
   orange-red banding toward the tops, tucked against the mountains, tall pines between them, grass between.
   It is the tauren burial ground; the wiki text says heroes are sent on by cleansing flame (funeral
   pyres/platforms), but no reference image of those was found, so treat that as unverified.
2. Traits: soft round rock shapes, pink-orange banding, pines, quiet.
3. Fixes: replace the recipe (`stone_circle` + 5 `grave_cairn`) with 6-10 new `az.rock.dome` / `az.rock.hoodoo`
   sprites (32x40 .. 48x64, pale pink with orange bands) plus 2-3 pines; optionally 1-2 funeral pyre platforms.

### Water wells: Thunderhorn, Winterhoof, Wildmane
Refs: `Thunderhorn_Waterwell.jpg`, `Winterhoof_Waterwell.jpg`, `Wildmane_Waterwell.jpg`.

1. All three are the **same tauren well-totem**, standing alone in open grass on a small bare tan dirt patch
   (radius about 8 yd): a low round grey stone dais (6-7 yd across, 1 yd high); on it four splayed log legs
   holding a carved wooden box with a big beast face and a small drum below; above that a wide shallow conical
   hide canopy (6-7 yd across) with a spiky red-brown fringe; on top a cross-pole with two long dark hides
   hanging. Total height 8-10 yd. Thunderhorn: beside the north road in flat grass with Thunder Bluff's cliffs
   behind. Winterhoof: at the edge of the southern hills, rock domes and the gate palisade in view. Wildmane:
   on a grassy slope north of Thunder Bluff. No buildings around them (a few Venture Co. goblins or
   Grimtotem at quest time).
2. Traits: tall silhouette with canopy and hanging hides, round stone base, bare dirt disc, nothing else.
3. Fixes: new `az.obj.water_well` (48x80, stone dais + canopy + hides) replacing `az.obj.well` (a European
   bucket well) in the three well recipes; drop the barrel/crate; paint a 4-tile DIRT disc under it.
   Remove `az.obj.well` from Bloodhoof's recipe and Thunder Bluff's STREET list.

### Stonetalon Pass (NW)
Refs: `Stonetalon_Pass_Entry_(Cataclysm).jpg`, `Stonetalon_Pass_Summit_(Cataclysm).jpg`.

1. A narrow dirt path climbing between pale tan rounded rock domes into the mountains. Big pines with thick
   red-brown trunks. Grimtotem hold it: one very tall teal-hex totem, rows of sharpened stakes angled outward
   (stake barricades), a small rubble/rock heap across the path. At the summit plateau: lush grass, pines, and
   a rounded boulder with a dark red painted kodo on it.
2. Traits: path-in-a-gully, stake barricades, tall totem, painted rock.
3. Fixes: replace the single `az.obj.stonetalon_pass` (generic grey rocks) with a placed path + 2-3 pale rock
   domes + `az.obj.stake_row` (new 32x16, also good for quilboar) + 1 tall totem; add `az.obj.painted_rock`
   (32x24) at the top.

### Great Gate (east, to the Barrens)
Refs: `The_Great_Gate.jpg`, `Cataclysm_Gates_of_Mulgore.jpg`.

1. All carved wood, no masonry. A long palisade of horizontal log walls with tall sharpened vertical posts
   (wall about 8 yd high) spanning the canyon; in the middle a gate of tall sharpened stakes bound with rope
   (about 10 yd wide, 10 yd tall) with a carved eagle/thunderbird emblem; flanking it two tower-totems (about
   20 yd): square carved base with a teal diamond emblem, two tiers of fur-fringed pagoda-like hide roofs,
   a carved eagle with spread teal-tipped wings on top; two tall flaming torch-totems beside the gate with a
   rope of hanging talismans strung between them. Ground on the outside is orange Barrens sandstone; on the
   Mulgore side, grass.
2. Traits: carved wooden eagle towers, fur roofs, stake gate, torch totems with talisman rope, long log wall.
3. Fixes: current `az.obj.great_gate` (64x48 = 8x6 yd, grey stone base, Horde red banners, bull skull) is
   both far too small and the wrong material. Split into pieces: `gate_tower` (48x160), `gate_doors`
   (80x80), `torch_totem` (16x96), `log_wall` tile (32x64), and place the wall across the whole pass.

### Wildlife
Refs: `Kodobeast.jpg`, `Mulgore_Wildlife.jpg`, `Golden_Plains.jpg`, `Plainstrider.jpg`, `Prairie_Wolf.jpg`,
`Young_Battleboar.jpg`, `Battleboar_Pen.jpg`, `Bristleback_Quilboar.jpg`, `Windfury_Harpy.jpg`.

| creature | real look | real size | ours | fix |
|---|---|---|---|---|
| kodo | massive grey/olive scaly hide (some brown-tan), huge humped shoulders, head carried low, big nose horn plus side horns and a bony frill, short thick legs | 6-8 yd long, 4 yd at shoulder (taller than a tauren) | `kodo` 32x24: grey body under a brown shaggy shell, reads as armadillo/turtle | remove the shell, scaly grey-olive, hump at the front; 48x40 |
| plainstrider (`tallstrider`) | flightless bird, tan-brown body, darker brown wing stubs, long grey-green striped legs, bony crested beak-head | about 3 yd tall | navy/blue body, grey neck, yellow legs | recolour to tan/brown + striped grey legs; size ok |
| prairie wolf | lean, pale straw-cream to yellow-tan fur | 1 yd at shoulder | `wolf` tan-grey | lighter, more yellow |
| young boar / battleboar | golden-orange with brown tiger stripes, cream chest ruff, brown spiky mane; Battleboar Pen's are armoured in blue-grey plate | 1.5 yd tall | plain brown boar | recolour; add armoured variant |
| Bristleback quilboar | upright boar-man, red-brown skin, huge crest of quills on head/back, tusks, rope belt, bone bracers | about 2.2 yd | manifest <=16x16 | 16x20 at least, quill crest the dominant shape |
| Windfury harpy | blue-feathered wings and skin, yellow-green striped bird legs with black talons | human size, 3-4 yd wingspan | manifest <=16x16 | 24x20 so the wings read |

---

## 2. The small camps

### Camp Narache (start camp, north part of Red Cloud Mesa)
Ref: `Camp_Narache.jpg`.

1. On the plateau's grass with a grey cliff wall and pines behind. About 100 yd across. Five buildings around
   a central open ring where the class trainers stand: the main tent (wounded braves; a big two-tier white
   tent, cone on top of a wide drooping skirt roof, on a dark wooden drum base, about 16-18 yd across and
   tall), the spirit lounge, the bakery tent, the armory tent (a long low hide-covered lodge of brown hide
   over arched poles) and a trader's tent. Six to eight **very tall totems** (10-14 yd) stand around the edge,
   each a thick column banded with teal hexagons outlined in red on weathered wood, some with horned/winged
   arms; one tall pole carries a carved eagle with spread plank wings. Brown hide windbreak screens strung
   between poles along the back. Tan dirt paths branch from the centre. Grass is bright lime.
2. Traits: (a) huge white stitched tents with brown stitching and drooping skirts, (b) a forest of tall hex
   totems, (c) open centre ring, (d) cliff + pines behind, (e) very few small props.
3. Fixes (recipe `Camp Narache`, now r=28 with 34 objects; `new_CampNarache.png` shows no recognisable camp,
   just trees, two tiny teepees, dummies, fires and a fat road):
   - Keep r about 24 but: 1 x main tent (new `az.obj.great_tent` 128x128 two-tier, or a much bigger
     `hut_large`), 2 x `hut_large`, 1 x long hide lodge (new `az.obj.hide_longhouse` 96x48), 1 x `tent`,
     7 x `totem_pole` (r 14-24), 1 x `eagle_totem`, 3 x hide windbreak (new, 48x32), 1 bonfire at the centre,
     2 training dummies, 1 drying rack, 1 hide stretcher.
   - Remove: haystack, signposts, barrels, torches, cooking pots, banners.
   - No pines or broadleaf trees inside r < 20; a pine line behind on the cliff side only.
   - Bristleback mobs belong outside the camp (they were inside in the shot).

### Bloodhoof Village (the one real village, on the Stonebull peninsula)
Refs: `Bloodhoof_Village.jpg`, `BloodhoofVillageStonebullLake.jpg`, `Stonebull_Lake.jpg`, `Fargaze_Mesa_2.jpg`.

1. About 150 x 120 yd on the low peninsula, lake on west, north and east. Buildings stand 20-40 yd apart with
   open grass between, joined by narrow tan paths. Pieces: the **great teepee** in the middle (white stitched
   cone about 20 yd tall on a round timber deck about 16 yd across with steps, a bundle of long crossed poles
   sticking out of the top); a cluster of two or three big white round tents on the west side (the inn is one
   of them) plus a long brown hide lodge; 4-6 tall totems between them; three "eagle" totems (a short pole on a
   round stone base with a carved figure and two big plank wings); a **timber lodge on stilts** with a sloped
   teal-grey roof right at the water edge (north shore); a large oval of bare dirt (about 25 yd) ringed with
   short wooden posts where NPCs sit; two wooden gate arches with hanging hides on the east side; a stable
   area with a few kodo. A handful of pines on the banks.
2. Traits: (a) the great teepee as the landmark, (b) a few huge white tents, not many small ones, (c) tall
   totems and eagle totems, (d) lots of open grass, (e) water around it, stilt lodge and bridge.
3. Fixes (recipe `Bloodhoof Village`, now 69 objects incl. 4 torches, 3 barrels, 2 crates, 3 signposts, 3
   haystacks, 3 grave cairns, 5 kodo pens, stone circle, 2 bucket wells, 2 cooking pots, 3 banners):
   - Keep: 1 `big_teepee` at r 0-4 (it is the centre, not r 8-16), 3 `hut_large`, 1 `inn`, 1 long hide
     lodge, 2 `tent`, 5 `totem_pole`, 3 `eagle_totem`, 1 `stilt_lodge` placed ON the shore (needs a
     "nearest shore" placement rule, not a random radius), 1 training ring (new `az.obj.post_ring` decal
     with posts, 96x64), 2 entrance arches (new `az.obj.gate_arch` 48x48), 1 `stable` with 2 kodo, 1 forge +
     anvil, 2 bonfires, 2 drying racks, 2 hide stretchers.
   - Remove: bucket wells, signposts, grave cairns, haystacks, stone circle, prayer flags, most torches,
     barrels/crates except 2-3 next to vendors, 4 of the 5 kodo pens, Horde banners (tauren camps fly few).
   - Raise the minimum spacing: big pieces at least 10 tiles apart (the `size` field: 12-16 for tents).
   - `big_teepee`, `eagle_totem` and `stilt_lodge` are in the manifest but not drawn yet, so the
     village currently has no landmark at all.

### Camp Sungraze (NE of Thunder Bluff)
Ref: `Camp_Sungraze.jpg`.

1. Tiny camp, whole thing about 30 yd: three tall tents tight around a campfire on a bare dirt patch (each
   tent about 8 yd at the base, 12-14 yd tall: white upper cone with brown stitches and crossed poles at the
   tip, a painted band of teal/red arrows, then a flared lower skirt of tan-brown hide with a big teal
   diamond motif); one very tall teal-hex totem; a round wooden frame with a stretched orange hide; a kodo
   skeleton (bones) on the grass; pines behind.
2. Traits: tightness, tall skirted tents, one totem, fire.
3. Fixes: recipe r 24 -> 10; 3 x `tent` (redrawn tall with skirt, 64x104) at r 4-8, 1 x `totem_pole`, 1 bonfire
   at r 0, 1 hide stretcher, 1 `kodo_bones`; remove hut_large, hut_small, haystack, torches, cooking pot,
   drying racks.

### Palemane Rock (gnoll camp, west)
Ref: `Palemane_Rock.jpg`.

1. At the foot of a tall pale grey cliff: a cave mouth framed by blue-grey boulders, pines in front, a
   conical grey rock mound; outside, a scruffy gnoll camp on trampled tan dirt in tall golden grass: a wooden
   lattice cage, a hide lean-to, small tripods, weapon racks, a crude small tent.
2. Traits: cave in grey boulders, pines, cage, golden grass.
3. Fixes: replace `rock_arch` (orange natural arch) with `az.obj.cave_mouth` (64x48 grey-blue boulders);
   add `az.obj.cage` (24x24), `az.obj.lean_to` (32x24), 1-2 tripods; keep 1 bonfire; drop `kodo_bones`.

### Venture Co. Mine (eastern cliffs) and Ravaged Caravan
Refs: `Venture_Co_Mine.jpg`, `Ravaged_Caravan.jpg`.

1. Mine: a timber portal set into a pale tan-grey rock face: two sloping buttresses of horizontal planks and
   a heavy beam lintel, dark tunnel with lantern glow, rails and a cart, a small iron lamp-post outside;
   grass and a pine right up to it. The wiki also lists a cliff entrance and a small lumber camp (cut log
   piles). Caravan: on a grassy mound by the lake, a ring of overturned goblin wagons (dark wood, red-brown
   shingle roofs, big iron-rimmed wheels), a barrel wagon, scattered crates, a smouldering tepee-shaped wood
   pile in the middle trailing black smoke.
2. Traits: plank portal in pale rock, rails/cart; dark-wood goblin wagons with rust shingles.
3. Fixes: `az.obj.mine_entrance` rock is orange-red, should be pale tan-grey; widen to 64x48 with plank
   buttresses. Goblin shacks: dark timber + rusty iron + red shingle roof is right; keep 2, add a log pile and
   rails. Ravaged Caravan: our `wagon` is a white-canvas pioneer wagon; redraw as a boxy dark goblin wagon
   with a shingle roof, tipped over, plus a black smoke fx.

### Bael'dun Digsite (west, in the mountainside)
Ref: `Bael'dun_Digsite.jpg`.

1. A quarry floor of trampled grass/dirt walled by **enormous dwarven timber retaining walls** (15-20 yd high,
   vertical logs with blue-steel bands and diagonal cross bracing), a red dwarven banner on the wall, a row of
   white canvas tents at the wall foot, a grey wooden shed/outhouse, crates and tools.
2. Traits: the giant braced timber wall dominates; tents tiny against it.
3. Fixes: add `az.obj.dwarf_wall` (64x128 piece, place 6-10 in an arc); keep 3 `dig_tent`, 1 shed, crates;
   drop the ore cart; scaffold optional.

### Quilboar land: Battleboar Pen, Brambleblade Ravine, Thornsnarl
Refs: `Battleboar_Pen.jpg`, `Brambleblade_Ravine.jpg`, `The_Thornsnarl.jpg`, `The_Thornsnarl_2.jpg`.

1. Battleboar Pen (south Red Cloud Mesa): a large patch of dark brown churned mud with blood-red stains,
   carcass meat and bones, enclosed by broken crooked grey wooden stake fences; giant curling thorn vines
   (trunk-thick, olive-brown, coiled, with big thorns) and dead trees behind; many armoured battleboars.
   Brambleblade Ravine (NE edge of Red Cloud Mesa): a dusty ravine between pale tan rock walls, cracked dry
   tan floor, quilboar huts of straw thatch domes with spiky logs leaning on them, huge thorn tendrils
   arching overhead, bonfires, orange haze. Thornsnarl: dark purple-brown soil with root patterns, giant
   coiled thorn vines, tall dead pine snags, a thorn-wrapped cage/totem.
2. Traits: giant coiled thorn vines (the signature), dark churned ground, straw-and-stake huts.
3. Fixes: none of these has a recipe or coordinates (estimates: Brambleblade about x 56, y 78 from the Kodo
   Rock note; Thornsnarl about x 55, y 88; Battleboar Pen SW of it). Add a DIRT_DARK ground, new
   `az.obj.thorn_vine` (48x64, 3 variants, coiled), `az.obj.stake_fence_broken` (32x24); redraw `thorn_hut`
   as a straw dome with leaning spiky logs (ours is a bony dome); use `dead_tree` here (redrawn as tall dead
   pine snags rather than white branching trees).

### Kodo Rock (classic, near Narache)
Ref: `Kodo_Rock.jpg`. A single dark blue-grey standing stone (about 3 yd tall) with faint carved symbols in
tall golden grass among pines. Our recipe uses two `kodo_bones`; replace with one `az.obj.standing_stone`
(16x32, dark blue-grey).

---

## 3. Thunder Bluff (short)

Refs: `tbref/*` (Thunderbluff-1600x.jpg etc.), `MulgoreArt.jpg`.

Four mesas with **sheer pale tan-grey cliffs** (bold vertical streaks, 100+ yd tall), flat grassy tops with
pines. On top: big round white "big top" tents ringed by posts, longhouses with teal-grey roofs, the tall
wind-rider tower, tall totems and wind-mill totems, rope bridges between rises, lift towers. Busy compared to
the plains, but still grass and pines between buildings. What we have is mostly right in structure
(`az.tb.cliff.face` is the right pale grey). Fixes: no `az.plant.tree` broadleafs at the cliff foot (visible in
`new_ThunderBluff.png`), use the redrawn tall pine; the plateau grass should get the same warm palette;
`az.obj.well` out of STREET.

---

## 4. Art-wide notes on our sprites

- `az.tb.pine` (used everywhere): saturated dark blue-green, a solid symmetrical cone, trunk hidden. WoW's
  Mulgore pine is olive/yellow-green with sunlit golden tips, **layered drooping tiers with gaps between**,
  a tall straight red-brown trunk with a flared base visible for the lower quarter to third, slightly
  irregular silhouette. Redraw at 32x96 (with 40x128 landmark variants) and let it cast a long soft shadow.
- `az.plant.tree` (acacia/oak) should not appear in Mulgore at all (only the Barrens side of the gate).
- `az.obj.totem_pole` is drawn 16x40 (manifest already asks 16x72) with stacked faces. Real Mulgore totems are
  thick columns (1.5-2 yd) 10-14 yd tall, mostly **teal hexagons outlined in dark red on pale weathered wood**,
  a carved face or horned head near the top, sometimes plank wings/horns as arms. 24x104 for the tall ones.
- Tents: `tent` 32x28 and `hut_small` 32x32 are 4 yd objects; real tents are 8 yd wide and 12-14 yd tall,
  off-white canvas with dark brown cross-stitched seams, a painted band, a flared hide skirt. `hut_large`
  48x40 is drawn as a squat tan dome; real big tents are tall, white and two-tiered.
- Mountains/mesas: pale beige-grey, not orange-red. `az.mesa.face`, `az.ground.mesa`, `az.mountain.*` and
  the minimap's ring colour need a pale palette; keep orange for Red Rocks and the Barrens.
- `az.obj.stone_circle` (grey standing slabs) has no counterpart in Mulgore; tauren sacred rings are small
  stones laid on the ground.

---

## 5. The 15 biggest mismatches (priority order)

1. **Too many trees, forest-like groves** (`new_prairie.png` reads as parkland woods): drop grove density to
   tight clumps far apart (about 1 tree per 400-800 tiles overall) so open grass dominates.
2. **Broadleaf acacia/oak trees in Mulgore**: remove `az.plant.tree` from the Mulgore scatter; pines only.
3. **Pine art and scale** (3x7 yd dark Christmas cone): redraw as a 32x96+ olive WoW pine with layered
   drooping tiers and a visible red-brown trunk.
4. **Grass colour and texture** (saturated mid-green with heavy dark dither): warm lime-gold, low-contrast,
   big golden swathes from low-frequency noise.
5. **Ground clutter** (flowers/clumps/stones/bushes on about 13 % of tiles): cut to about 4 %, mostly golden
   grass tufts; flowers about 1/300.
6. **Stonebull Lake sunk in a pit with stepped cliff banks**: flatten shore relief to water level and add a
   2-tile sand band; no terrace walls.
7. **Water colour** (deep navy, noisy): pale calm turquoise, see-through shallows.
8. **Roads 3-5 tiles of red-brown dirt**: 1-1.5 tile pale grey-beige gravel trails with soft edges, less wobble.
9. **Camps are prop clutter fields** (Bloodhoof recipe has 69 objects, Narache 34): cut to the 8-12 big pieces
   listed above; delete torches, pots, barrels, crates, signposts, haystacks, cairns, kodo pens.
10. **Buildings far too small** (tents 4 yd, huts 6 yd): tents 64x104, big tents 96-128 px wide, great
    teepee 128x176; raise recipe footprints so they sit 10+ tiles apart.
11. **Bloodhoof has no landmark**: draw `big_teepee`, `eagle_totem`, `stilt_lodge`; put the teepee at the
    centre and the stilt lodge on the shore; add the lake rope bridge and the east gate arches.
12. **Water wells drawn as European bucket wells**: new 48x80 canopy well-totem on a round stone dais with a
    dirt disc; remove bucket wells from Bloodhoof and Thunder Bluff.
13. **Totems short and wrong pattern**: 24x104 thick columns with teal-hex-in-red bands; 6-8 of them ring
    Camp Narache.
14. **Mountain/mesa rock is red-orange**: repaint the zone's mountain ring and Red Cloud Mesa cliffs pale
    beige-grey; Red Cloud Mesa top is grass, not mesa rock with spires.
15. **Landmark sprites wrong** (stone-and-banner Great Gate at 8x6 yd, orange rock arch at Palemane, grey
    Stonehenge circles, armadillo-shell kodo, blue plainstriders): rebuild the gate as carved wooden eagle
    towers + stake gate at real size, cave mouth at Palemane, ground offering ring at Fargaze, scaly
    48x40 kodo, brown plainstriders.

Missing outright (no recipe/coords): Battleboar Pen, Brambleblade Ravine, Thornsnarl, Fargaze Mesa; they need
the thorn-vine kit and positions before they can look like anything.
