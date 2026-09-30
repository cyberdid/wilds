"""The Azeroth art contract: the manifest is coherent, nothing is drawn that it does not list,
and every module declared done in ``AZEROTH_DONE`` satisfies it completely."""

import collections

from wilds.azeroth import manifest
from wilds.gfx.sprites import AZEROTH_DONE, AZEROTH_MODULES, load_azeroth


def test_manifest_modules_match_the_sprite_modules():
    assert tuple(f"az_{k}" for k in manifest.required()) == AZEROTH_MODULES


def test_manifest_is_coherent():
    names = [n.name for needs in manifest.required().values() for n in needs]
    dupes = [n for n, c in collections.Counter(names).items() if c > 1]
    assert not dupes, dupes
    assert all(n.startswith("az.") for n in names)
    for needs in manifest.required().values():
        for n in needs:
            assert n.dims()[0] > 0 and n.frames >= 1


def test_the_manifest_is_the_size_the_plan_says():
    s = manifest.summary()
    total = sum(v["sprites"] for v in s.values())
    assert 450 < total < 700, total


def test_creature_and_portrait_lists_come_from_the_data():
    assert {"kodo", "tallstrider", "quilboar", "harpy"} <= set(manifest.species())
    assert "baine_bloodhoof" in manifest.portraits()
    assert "tallstrider" in manifest.hostile_species() and "rabbit" not in manifest.hostile_species()


def test_done_modules_satisfy_the_manifest():
    registry = load_azeroth()
    done = [m[3:] for m in AZEROTH_DONE]
    problems = manifest.check(registry, done) if done else []
    assert not problems, "\n".join(problems[:40])


def test_nothing_is_drawn_that_the_manifest_does_not_list():
    registry = load_azeroth()
    wanted = {n.name for needs in manifest.required().values() for n in needs}
    stray = sorted({name.split("@")[0] for name in registry.names("az.")} - wanted)
    assert not stray, stray
