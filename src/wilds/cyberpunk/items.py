"""City goods: trade items and cyberware, in basic and alphaware grades (stage 6,
stretch) - Shadowrun's own grade ladder goes further (beta/delta), left out here
since two grades already carry the essence-vs-nuyen dilemma the mechanic is for."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ItemInfo:
    name: str  # Ukrainian display name
    glyph: str
    price: int  # nuyen, base vendor price
    cyberware: bool = False
    essence_cost: float = 0.0
    heal: int = 0  # hp restored by `use` (stage: fail-forward gives hp something to spend)
    note: str = ""  # English note for the LLM


# alphaware costs roughly 3x and halves the essence hit - the same "pay more,
# lose less of yourself" trade the tabletop grade ladder is built on
_ALPHA_PRICE_MULT = 3.0
_ALPHA_ESSENCE_MULT = 0.5


def _alpha(base_key: str, info: ItemInfo) -> ItemInfo:
    return ItemInfo(f"{info.name} (альфа)", info.glyph.upper(), round(info.price * _ALPHA_PRICE_MULT),
                    cyberware=True, essence_cost=round(info.essence_cost * _ALPHA_ESSENCE_MULT, 2),
                    note=f"alphaware grade: {_ALPHA_ESSENCE_MULT:.0%} of {base_key}'s essence cost, "
                         f"{_ALPHA_PRICE_MULT:.0f}x the price")


_BASE_CYBERWARE = {
    "cyber_eye": ItemInfo("кіберочі", "o", 1200, cyberware=True, essence_cost=0.3,
                          note="cyberware: sharper vision, small essence cost"),
    "cyber_arm": ItemInfo("кіберрука", "a", 3500, cyberware=True, essence_cost=1.2,
                          note="cyberware: stronger grip and unarmed damage, essence cost"),
    "dermal_plating": ItemInfo("дермальна броня", "D", 5000, cyberware=True, essence_cost=1.5,
                               note="cyberware: subdermal armor, essence cost"),
}

ITEMS: dict[str, ItemInfo] = {
    "credstick": ItemInfo("кредчип", "$", 0, note="unused; nuyen is tracked directly, not as an item"),
    "synth_noodles": ItemInfo("синтетична локшина", "n", 8, note="cheap food"),
    "stim_patch": ItemInfo("стим-пластир", "+", 45, heal=30, note="quick healing patch, `use` for +30 hp"),
    "burner_deck": ItemInfo("одноразовий комлінк", "c", 60, note="anonymous comm device, useful for shady deals"),
    "pistol": ItemInfo("важкий пістолет", "/", 400, note="sidearm, attack 6"),
    "armor_jacket": ItemInfo("бронежилет", "[", 350, note="light armor"),
    "trinket": ItemInfo("сувенір", "*", 20, note="junk worth a little to a fence"),
    "corp_data_chip": ItemInfo("корпоративний чип даних", "d", 900, note="hot data, risky to be caught with"),
    **_BASE_CYBERWARE,
    **{f"{k}_alpha": _alpha(k, v) for k, v in _BASE_CYBERWARE.items()},
}
