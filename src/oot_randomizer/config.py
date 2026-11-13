from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RandomizerConfig:
    seed: int = 0
    goal: str = "ganon"
    logic: str = "glitchedless"
    shuffle_items: bool = True
    shuffle_dungeons: bool = True
    shuffle_songs: bool = True
    shuffle_event_items: bool = True
    shuffle_npc_items: bool = True
    shuffle_skull_rewards: bool = True
    use_logic: bool = True
    logic_file: str | None = None
    all_locations_reachable: bool = True
    bombchus_in_logic: bool = True
    one_major_per_dungeon: bool = False
    # Shopsanity: shop shelf slots randomized per shop (0 = off, max 4).
    shop_slots_per_shop: int = 2
    # Loose overworld heart pieces hold randomized pickupable items.
    shuffle_heart_pieces: bool = True
    skip_intro: bool = False
    output_path: str | None = None
    item_pool_limit: int = 12
    dungeon_pool_limit: int = 6

    def normalized_seed(self) -> int:
        return self.seed if self.seed != 0 else 1
