"""The text-grid pixel-art DSL: parsing, validation, transforms, rendering."""

import pytest

from wilds.gfx.palette import PALETTE
from wilds.gfx.pixelart import (Art, art, crop, emissive_rgba, erase, grid, mirror, outline_grid, overlay,
                                pad, recolor, shift, swap, symmetric)
from wilds.gfx.registry import Registry


def test_grid_strips_indentation_and_blank_edges():
    g = grid("""

        .ab.
        c..d

    """)
    assert g == (".ab.", "c..d")


@pytest.mark.parametrize("bad", ["", "ab\nabc", "a b\nabc"])
def test_grid_rejects_empty_ragged_and_spaces(bad):
    with pytest.raises(ValueError):
        grid(bad)


def test_art_validates_legend_palette_size_and_anchor():
    with pytest.raises(ValueError, match="legend"):
        art("ab")  # 'a' and 'b' have no legend entry
    with pytest.raises(KeyError):
        art("a", legend={"a": "no_such_colour"})
    with pytest.raises(ValueError):
        art("aa", "aaa", legend={"a": "moss2"})
    with pytest.raises(ValueError):
        art("aa", legend={"a": "moss2"}, anchor=(5, 0))
    a = art("kw", legend={})  # k/w come from the default legend
    assert a.size == (2, 1) and a.ground_anchor == (1, 0)


def test_transforms():
    g = grid("ab.\n.c.")
    assert mirror(g) == (".ba", ".c.")
    assert shift(g, 1, 0) == (".ab", "..c")
    assert pad(g, left=1, bottom=1) == (".ab.", "..c.", "....")
    assert crop(g, 1, 0, 2, 2) == ("b.", "c.")
    assert overlay(g, grid("x"), 2, 1) == ("ab.", ".cx")
    assert erase(g, grid("x"), 0, 0) == (".b.", ".c.")
    assert swap(g, {"a": "z"}) == ("zb.", ".c.")
    assert symmetric("ab") == ("abba",)
    assert symmetric("ab", center=True) == ("aba",)
    assert outline_grid(grid("...\n.a.\n..."), "k") == (".k.", "kak", ".k.")


def test_rgba_colours_alpha_and_auto_outline():
    a = art("...\n.a.\n...", legend={"a": "moss3"}, outline="ink")
    data = a.rgba()
    px = lambda x, y: tuple(data[(y * 3 + x) * 4:(y * 3 + x) * 4 + 4])  # noqa: E731
    assert px(1, 1) == (*PALETTE["moss3"], 255)
    assert px(1, 0) == (*PALETTE["ink"], 255)  # outline next to the pixel
    assert px(0, 0) == (0, 0, 0, 0)  # diagonal stays transparent
    glass = art("g", legend={"g": "glowcyan:96"})
    assert tuple(glass.rgba()) == (*PALETTE["glowcyan"], 96)


def test_translucent_pixels_do_not_grow_an_outline():
    a = art("...\n.g.\n...", legend={"g": "glowcyan:80"}, outline="ink")
    assert a.rgba()[3::4].count(255) == 0


def test_recolor_maps_names_and_keeps_alpha():
    a = art("ab", legend={"a": "suit2", "b": "glowcyan:90"})
    b = recolor(a, {"suit2": "lira2", "glowcyan": "glowpink"})
    assert b.legend["a"] == "lira2" and b.legend["b"] == "glowpink:90"
    assert a.legend["a"] == "suit2"  # original untouched


def test_emissive_layer_only_holds_glowing_pixels():
    a = art("ab", legend={"a": "moss2", "b": "neon_cyan"})
    data = emissive_rgba(a)
    assert data[3] == 0 and data[7] == 255
    assert emissive_rgba(art("a", legend={"a": "moss2"})) is None


def test_frame_index_loops_or_holds():
    a = art("a", "b", legend={"a": "moss2", "b": "moss3"}, fps=4)
    assert [a.frame_index(t) for t in (0, 0.26, 0.51)] == [0, 1, 0]
    once = Art(a.frames, a.legend, fps=4, loop=False)
    assert once.frame_index(10) == 1


def test_registry_names_variants_and_duplicates():
    reg = Registry()
    one = art("a", legend={"a": "moss2"})
    for n in ("x.t@1", "x.t@0", "x.t@10", "x.solo"):
        reg.add(n, one)
    assert reg.variants("x.t") == ["x.t@0", "x.t@1", "x.t@10"]
    assert reg.variants("x.solo") == ["x.solo"]
    assert "x.t" in reg and reg.resolve("nope", "x.solo") == "x.solo"
    with pytest.raises(ValueError):
        reg.add("x.solo", one)
    with pytest.raises(ValueError):
        reg.add("Bad Name", one)
