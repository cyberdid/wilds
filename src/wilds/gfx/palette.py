"""The master palette: every pixel of every sprite is one of these named colours.

Sprites never use raw RGB - a legend maps each grid character to a *name* here,
so the whole game shares one hand-tuned set of ramps (dark -> light, hue-shifted:
shadows lean toward violet/blue, highlights toward warm yellow) and a recolour
(race skin, role outfit, district theme) is just a name-to-name mapping.

Ramps are numbered from 0 (darkest) upward, e.g. ``moss0`` .. ``moss5``.
"""

from __future__ import annotations

RGB = tuple[int, int, int]

PALETTE: dict[str, RGB] = {}
RAMPS: dict[str, list[str]] = {}


def _hex(value: str) -> RGB:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _ramp(prefix: str, *hexes: str) -> None:
    names = []
    for i, h in enumerate(hexes):
        name = f"{prefix}{i}"
        PALETTE[name] = _hex(h)
        names.append(name)
    RAMPS[prefix] = names


def _named(**colors: str) -> None:
    for name, h in colors.items():
        PALETTE[name] = _hex(h)


# --- neutrals ------------------------------------------------------------------
_named(
    void="#07060d",   # never-seen space / unexplored map
    ink="#140f1e",    # the standard 1px outline: warm near-black, never pure black
    ink2="#231a33",   # secondary outline / deepest shadow inside a sprite
    white="#f2f0f7",
    black="#000000",
)
_ramp("grey", "#2b2838", "#45425a", "#6a6782", "#9895ad", "#c8c6d6")
_ramp("bone", "#4a3f3a", "#7a6a5e", "#a8968a", "#d6c7b8", "#f5ece0")

# --- Tau-7 surface --------------------------------------------------------------
_ramp("moss", "#0e2426", "#173a3a", "#22574f", "#347a63", "#55a077", "#8ccc93")
_ramp("dust", "#2d1410", "#4e2217", "#74351f", "#9c4f2b", "#c4713c", "#e6a063")
_ramp("flora", "#1c1233", "#2f1f57", "#4b3182", "#6d4bb0", "#9876d6", "#c7a9f2")
_ramp("spore", "#3d0f2a", "#6e1a4a", "#a82a6e", "#e04a96", "#ff85c0", "#ffd0e8")
_ramp("water", "#0a1230", "#122252", "#1c3a7a", "#2c5fa8", "#4f93d1", "#9fd8f5")
_ramp("rock", "#18161f", "#2c2939", "#454058", "#635d7a", "#8a849f", "#b9b3c9")
_ramp("ore", "#6b3a1a", "#c07a2a", "#f2b24a")
_ramp("cryst", "#1f6f7a", "#45c7d1", "#b5fff7")
_named(glowcyan="#5ff5e6", glowpink="#ff7ad9", glowlime="#c4ff6b", glowviolet="#c78cff")

# --- metal, machines, wrecks ------------------------------------------------------
_ramp("steel", "#10151f", "#1d2838", "#2f4257", "#4a6680", "#7291ab", "#a8c3d6")
_ramp("stat", "#2a2f38", "#4e5866", "#8a96a3", "#c9d2da", "#eef2f5")  # Kepler-9 station panels
_ramp("hive", "#120c1f", "#2a1640", "#4a2a63", "#7a4a8f", "#b07ac2")  # precursor biomech
_named(hivegl="#7dffc8", hazard="#f2c230", hazard_dark="#8a6512", podorange="#f07a2a",
       statacc="#e8762c")
_ramp("fire", "#5c1010", "#a6231a", "#e8501f", "#ff9a2e", "#ffd76a", "#fff6c8")
_ramp("tent", "#5a2e14", "#9a5320", "#d27f30", "#f2ad5b", "#ffd99a")

# --- Tau-7 life ------------------------------------------------------------------
_ramp("suit", "#4a1f0e", "#8a3a14", "#d2601c", "#f59038", "#ffc070")     # the survivor
_ramp("lira", "#2e0f33", "#5c1a66", "#9a2aa6", "#d24ad6", "#f59cf2")     # the second survivor
_ramp("hound", "#1f2a0e", "#3d5418", "#6a8a22", "#a6c93a", "#dcf57a")
_ramp("brute", "#2e1406", "#5a2a0c", "#8f4614", "#c96b22", "#f09a45")
_ramp("red", "#3a0a10", "#7a1420", "#c42230", "#ff4a4a", "#ff9a8a")

# --- people ------------------------------------------------------------------------
_ramp("skin", "#3b2219", "#6e3f2a", "#a8674a", "#d99a76", "#f5c9a8")
_ramp("elf", "#5a4a58", "#9a8494", "#d6c2cc", "#f7ebef")
_ramp("ork", "#1f2a1a", "#3a4f2c", "#5e7a44", "#8aa864", "#b9d48f")
_ramp("troll", "#1d2230", "#3a4258", "#5f6a85", "#8e99b3", "#bcc5d9")
_named(hair_black="#1a1418", hair_brown="#5a3420", hair_blond="#e0b050", hair_red="#b0401c",
       hair_copper="#d8682c", hair_white="#e8e4ee", hair_blue="#3a6aff", hair_pink="#ff4ab0",
       hair_green="#3aff8a", tusk="#efe6c8", blush="#e0706a")
_ramp("jacket", "#5a4a0e", "#a88a1a", "#e8c22a", "#fff07a")   # the city runner (yellow @)
_ramp("denim", "#141c33", "#223058", "#34498a", "#5a74b8")
_ramp("leather", "#140e10", "#261a1c", "#3d2a2c", "#5c4043")
_ramp("olive", "#1c2212", "#34401f", "#56663a", "#7f915a")

# --- the city ------------------------------------------------------------------------
_ramp("city", "#0b0a17", "#151429", "#221f3d", "#34305a", "#4d4880", "#726ca6")
_ramp("asph", "#0f0f16", "#1a1a24", "#272733", "#383847", "#50505f")
_ramp("conc", "#25242e", "#3a3945", "#53525f", "#72717e", "#9998a4")
_ramp("rust", "#2a140c", "#50261a", "#7a3c22", "#a85a30", "#d4844e")
_ramp("glass", "#0f1a2a", "#1a3050", "#2a5080", "#4a80b8", "#8ac0e8")
_ramp("sand", "#3a2a14", "#6a4c24", "#9c7338", "#c9a055", "#ecd08a")

# --- Mulgore surface ---------------------------------------------------------------
_ramp("prairie", "#3d4b22", "#5c6d2b", "#7a8834", "#97a541", "#b7be50", "#d3d466")
_ramp("straw", "#4b4526", "#706331", "#928144", "#b09c53", "#c7b763", "#ddce7b")
_ramp("earth", "#33281b", "#51402a", "#705638", "#8e6b43", "#ad8653", "#c8a069")
_ramp("mesa", "#302019", "#4a2b1d", "#673821", "#854626", "#a75b31", "#c87942")
_named(
    neon_pink="#ff2bd6", neon_pink_dim="#8a1a78",
    neon_cyan="#29f0ff", neon_cyan_dim="#127a88",
    neon_green="#3dff6e", neon_green_dim="#1a7a38",
    neon_yellow="#ffe53d", neon_yellow_dim="#8a7a1a",
    neon_red="#ff3348", neon_red_dim="#7a1422",
    neon_orange="#ff8a1f", neon_violet="#9a4aff",
    win_warm="#ffc75a", win_cold="#8ae8ff", win_dark="#1a2036",
    cont_red="#8a2a22", cont_blue="#22508a", cont_green="#2a6a3a", cont_yellow="#b08a22",
    gold0="#6a4a12", gold1="#c8961e", gold2="#ffd24a", gold3="#fff2b0",
    chrome0="#3a4250", chrome1="#7a8698", chrome2="#c0cad8", chrome3="#f4f8ff",
)


# Colours that emit light: pixels painted with them are redrawn after the night
# light map, so neon, screens, eyes, flames and bioluminescence glow in the dark
# without every sprite needing its own light source.
EMISSIVE = frozenset({
    "glowcyan", "glowpink", "glowlime", "glowviolet", "hivegl", "cryst2", "spore5",
    "fire3", "fire4", "fire5", "win_warm", "win_cold",
    "neon_pink", "neon_cyan", "neon_green", "neon_yellow", "neon_red", "neon_orange", "neon_violet",
})


def rgb(name: str) -> RGB:
    """Colour of a palette name; raises KeyError with a helpful message."""
    try:
        return PALETTE[name]
    except KeyError:
        raise KeyError(f"unknown palette colour '{name}'") from None


def mix(a: RGB, b: RGB, t: float) -> RGB:
    """Linear blend of two colours, t=0 -> a, t=1 -> b (used by lighting, not sprites)."""
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t),
            round(a[2] + (b[2] - a[2]) * t))
