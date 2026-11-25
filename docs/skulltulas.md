# Gold Skulltulas

There are two separate things called "Gold Skulltula" in the randomizer. Only one of them is shuffled today.

| Kind | Where it is defined | Randomized? |
|------|--------------------|-------------|
| House of Skulltula rewards (10, 20, 30, 40, 50 tokens) | [skulltula_rewards.py](../src/oot_randomizer/skulltula_rewards.py) | Yes. The item in each reward slot is shuffled. |
| Field Gold Skulltulas (the spiders in the world) | `[regions.X.skulltulas]` in `logic\world\**\*.toml` | No. Each one always holds one `Item_Token_Gold`. |

## Field Gold Skulltulas (logic only)

Each entry is a logic location: a name and the requirement to reach it. Every entry always holds a token. [planner.py](../src/oot_randomizer/planner.py) fixes each one to `Item_Token_Gold` in `plan_seed`. The ROM is not patched for these spots.

The total must stay at 100. `TOTAL_TOKENS` in [world_logic.py](../src/oot_randomizer/world_logic.py) is the check. `ShippedWorldTests` in [test_world_logic.py](../tests/test_world_logic.py) fails if the count is wrong.

### Move a spot to another region

1. Find the line in `logic\world\**\*.toml`, under `[regions."X".skulltulas]`.
2. Cut the line and paste it under the new region's `[regions."Y".skulltulas]` table. Create the table if it does not exist. Edit the requirement if the new region needs a different rule.
3. Do not list the same name in `locations` as well. The loader rejects that.
4. Run the tests:

   ```powershell
   .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
   ```

Pot and other nearby objects are not Gold Skulltulas. For example, ootrr lists four Haunted Wasteland pots near a skulltula. They are not tokens, so they do not go in this table.

### Placeholders

A name can be kept as a placeholder when its exact spot is not confirmed yet. `LLR GS Rain Shed` is one. Keep the count at 100 while it is a placeholder, and update the region when the location is confirmed.

## Making field Gold Skulltulas randomizable (not built)

Doing this would be new work, similar to the House rewards. Roughly:

1. Find the grant for each field skulltula in the NUP event flow dumps. Use the approach in [adding_npc_grants.md](./adding_npc_grants.md).
2. Patch that grant so it gives the assigned item. Follow [skulltula_rewards.py](../src/oot_randomizer/skulltula_rewards.py) as the model.
3. In `planner.plan_seed`, stop fixing those spots to `Item_Token_Gold`. Add them to the shuffle pool instead.
4. Check that the item pool still gives the right number of tokens and that the logic still reaches vanilla beatable.

Until steps 1 to 3 exist, moving a field spot in the TOML changes only where logic expects the player to find it. It does not change what is in the world.
