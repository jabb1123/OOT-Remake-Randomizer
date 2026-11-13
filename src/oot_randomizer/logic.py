from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LocationCheck:
    name: str
    region: str
    required_items: tuple[str, ...]


DEFAULT_LOCATION_CHECKS: tuple[LocationCheck, ...] = (
    LocationCheck("Kokiri Forest", "overworld", ()),
    LocationCheck("Deku Tree", "dungeon", ("Kokiri Sword",)),
    LocationCheck("Forest Temple", "dungeon", ("Bomb Bag", "Hookshot")),
    LocationCheck("Fire Temple", "dungeon", ("Bomb Bag", "Hookshot", "Fire Arrows")),
    LocationCheck("Water Temple", "dungeon", ("Hookshot", "Ice Arrows")),
    LocationCheck("Shadow Temple", "dungeon", ("Bomb Bag", "Hookshot", "Lens of Truth")),
    LocationCheck("Spirit Temple", "dungeon", ("Magic Bean", "Hookshot", "Light Arrows")),
    LocationCheck("Gerudo Training Grounds", "dungeon", ("Magic Bean", "Hookshot")),
    LocationCheck("Bottom of the Well", "dungeon", ("Lens of Truth",)),
    LocationCheck("Ganon's Tower", "dungeon", ("Light Arrows", "Master Sword")),
)


class LogicEngine:
    """Simple OOT-inspired access evaluator.

    This is intentionally a deterministic, seedable logic model used to show that
    item placement and access rules can be evaluated before any ROM byte patching
    is attempted.
    """

    def __init__(self, logic: str = "glitchedless") -> None:
        self.logic = logic

    def _baseline_inventory(self) -> set[str]:
        return {"Kokiri Sword", "Deku Sticks", "Bomb Bag", "Bow"}

    def evaluate(self, item_pool: list[str]) -> list[str]:
        if self.logic == "all_locations":
            return [check.name for check in DEFAULT_LOCATION_CHECKS]

        inventory = set(self._baseline_inventory())
        inventory.update(item_pool)

        reachable: list[str] = []
        for check in DEFAULT_LOCATION_CHECKS:
            if all(item in inventory for item in check.required_items):
                reachable.append(check.name)

        if self.logic == "casual":
            return reachable

        if self.logic == "glitchedless":
            return reachable

        raise ValueError(f"Unsupported logic preset: {self.logic}")
