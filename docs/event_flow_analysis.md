# Extracting and Analyzing Event Flow Files

This covers how to pull an event flow file out of the `.nup`, decode it, and read or search what it does. The example is `Dm_DeathMtTrail_0025.bfevfl.zs`. The same steps work for other `.zs` files in the romfs. Only the parser changes.

## What the file is

A `.bfevfl.zs` is a Nintendo event flow (BFEVFL). It is a graph of events that runs a room's scripted logic: cutscenes, NPC movement, item grants, and gates that branch on game state.

- Location in the romfs: `romfs/Event/EventFlow/<Room>.bfevfl.zs`. The name is `<Scene>_<Room>`, for example `Dm_DeathMtTrail_0025`.
- Storage: ZSTD-compressed, with a per-type dictionary from `ZsDic.pack`. You must decompress before parsing.
- Copies: `nup list` shows the example twice. Index `16419` is in the **base** package. Index `202423` is in the **update** package (`romfs_dir 600`). Both are byte-identical today.

## Prerequisites

- Session venv: `C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\venv\Scripts\python.exe`. It has `evfl` (1.3.0, third-party from leoetlino/evfl) and `zstandard`. Both are in [pyproject.toml](../pyproject.toml).
- The `nup` reference package at [nup/tools/nup](../nup/tools/nup). It is used by `nup list` and `nup extract`.
- `ZsDic.pack` in the project root, next to the randomizer.
- Set `PYTHONPATH` to `src` for the randomizer modules, and to `nup\tools\nup` for the CLI.

The examples below use these shell variables:

```powershell
$py  = "C:\Users\jabb1123\.copilot\session-state\aa09e5ec-62eb-4ee7-bbd4-90178d07a405\files\venv\Scripts\python.exe"
$rom = "C:\Users\jabb1123\Desktop\Roms\The Legend of Zelda Ocarina of Time + U2\The Legend of Zelda Ocarina of Time   U2.0.0.nup"
```

## 1. Find the file

```powershell
$env:PYTHONPATH = "C:\Users\jabb1123\Desktop\Roms\oot_randomizer\nup\tools\nup"
& $py -c "import sys; from nup.cli import main; sys.argv=['nup','list',r'$rom']; main()" > temp\nup_list.txt
Select-String -Path temp\nup_list.txt -Pattern 'Dm_DeathMtTrail_0025.bfevfl'
```

Each line is `index  size  codec  name`. The index is what `NupReader.read_file(index)` takes. The list is large (about 370k lines), so write it to a file and search it.

## 2. Extract (optional)

Use this when you want a file on disk to inspect with other tools:

```powershell
& $py -c "import sys; from nup.cli import main; sys.argv=['nup','extract',r'$rom',r'temp\flows','--package','base','--subtree','romfs/Event/EventFlow']; main()"
```

- The output is flat: all 902 flow files go into the one destination folder. Two files with the same name would collide, so use step 3 for anything that needs the exact copy.
- The extracted files are still compressed. The magic bytes are `28 B5 2F FD` (ZSTD), and the size matches the listing (15,524 bytes for the example).

## 3. Decompress and parse

Save this as a script (for example `dump_flow.py`) and run it with `& $py dump_flow.py`:

```python
import sys, collections
sys.path.insert(0, r"C:\Users\jabb1123\Desktop\Roms\oot_randomizer\src")
sys.path.insert(0, r"C:\Users\jabb1123\Desktop\Roms\oot_randomizer\nup\tools\nup")

from nup.read import NupReader
from nup.access import iter_children
from oot_randomizer.nup_chest_patcher import _load_dicts_from_sarc, _decompress
import evfl
from evfl.event import ActionEvent, SwitchEvent, SubFlowEvent

ROM = r"C:\Users\jabb1123\Desktop\Roms\The Legend of Zelda Ocarina of Time + U2\The Legend of Zelda Ocarina of Time   U2.0.0.nup"
ZSDIC = r"C:\Users\jabb1123\Desktop\Roms\oot_randomizer\ZsDic.pack"
NAME = "Dm_DeathMtTrail_0025.bfevfl.zs"

def find_child(r, dir_index, name):
    for c in iter_children(r, dir_index):
        if c.name.decode("utf-8", "surrogateescape") == name:
            return c
    return None

dicts = _load_dicts_from_sarc(open(ZSDIC, "rb").read())
r = NupReader(ROM)
d = r.packages[0].romfs_dir                       # 0 = base package
for part in ("Event", "EventFlow", NAME):
    node = find_child(r, d, part)
    d = node.index
raw = _decompress(r.read_file(d), dicts)           # ZSTD + dictionary
r.close()

flow = evfl.EventFlow()
flow.read(raw)                                     # bytes, not a BytesIO
fc = flow.flowchart
print("events:", len(fc.events), dict(collections.Counter(type(e.data).__name__ for e in fc.events)))

for ev in fc.events:
    dd = ev.data
    if isinstance(dd, ActionEvent):
        print(ev.name, "ACT", dd.actor.v.identifier.name, dd.actor_action.v, dd.params.data if dd.params else "")
    elif isinstance(dd, SwitchEvent):
        print(ev.name, "SW", dd.actor.v.identifier.name, dd.actor_query.v,
              {k: v.v.name for k, v in dd.cases.items()})
    elif isinstance(dd, SubFlowEvent):
        print(ev.name, "SUB", dd.res_flowchart_name, dd.entry_point_name)
```

Notes on the script:

- `_decompress` picks the right dictionary from the frame header. You do not need to pass the dictionary ID.
- The decompressed bytes are the raw BFEVFL. Write them to disk if you want to diff two versions.

## 4. Read the output

The example flow has 211 events: 169 `ACT`, 14 `Fork`, 14 `Join`, 13 `SUB`, and 1 `SW`. The first lines look like this:

```
Event9  ACT Npc_Navi EventWarpToTargetPosAndRot
Event26 SUB GetPouchContent GetPouchContentByActorName
Event25 SUB  C01
```

| Kind | What it means | What to look at |
|---|---|---|
| `ActionEvent` (`ACT`) | Tells an actor to do something | Actor name and action. Params hold the arguments. |
| `SwitchEvent` (`SW`) | Branches on game state | The query (`GameDataActor.EventQueryIsGameDataBool`, `PouchSystemActor.EventQueryIsExistInPouch`, and so on) and the case map. |
| `SubFlowEvent` (`SUB`) | Calls another flow or entry point | Flow name and entry point. An empty flow name means the same file. |
| `ForkEvent` / `JoinEvent` | Runs branches in parallel and joins them | Structure only. |

Event names (`Event9`, `Event26`) are unique only within one file. Use the flow name plus the event name as the key when you combine results.

## 5. Analysis recipes

- **Find item grants:** look for `SUB` nodes into `GetPouchContent` or `Dm_SY_GetInEvent/*`, and `ACT` nodes that carry an item name in their params. [npc_grants.py](../src/oot_randomizer/npc_grants.py) documents the grant shapes.
- **Find gates:** look for `SW` nodes that read an `IsGet.*` flag or check the pouch. A gate on a vanilla item can route a randomized item to the wrong branch. See [adding_npc_grants.md](./adding_npc_grants.md) step 2.
- **Search for a name across the file:** names are stored as plain null-terminated strings, so you can search the decompressed bytes directly:

  ```python
  raw.find(b"Item_Melody_ZeldaLullaby\x00")
  ```

  [songs.py](../src/oot_randomizer/songs.py) uses this approach for `patch_bfevfl_songs`.
- **Dump every flow:** run the pattern in the session `files\recon\all_flows_decoded.txt` workflow. It loops over every `Event/EventFlow/*.bfevfl.zs` and writes one line per `ACT`, `SW`, and `SUB` node. Then search the output with `Select-String`.

## 6. Changing a flow

Use `NupChestPatcher.replace_file(filename, transform)` from [nup_chest_patcher.py](../src/oot_randomizer/nup_chest_patcher.py). It decompresses the file, passes the bytes to your `transform`, recompresses with the original dictionary, and updates the TOC. Do not write the NUP yourself. The grant and song patches both go through this path.

## Pitfalls

- **Two copies.** The base package (index 16419) and the update package (index 202423) hold identical files today. The randomizer patches the base copy. If a patch seems to do nothing in-game, check which copy the game loads, and compare hashes to see if they still match.
- **Parse bytes, not a stream.** Use `EventFlow().read(raw)`. Passing a `BytesIO` does not work.
- **`res_flowchart_name` can be empty.** An empty name means a call within the same file.
- **Flat extract collides.** `nup extract` flattens the folder. Read individual files through `NupReader` when the name is ambiguous.
- **Dictionary required.** Decompression fails without `ZsDic.pack`. Keep it in the project root, next to the randomizer.
- **Not every `.zs` is an event flow.** `AnimationEvent/Animation/*.anim.baev.zs` files decompress to a `BFFH` container (`Nintendo.AnimationEvent`), and `evfl` rejects them. Check the first 8 bytes for `BFEVFL` before parsing.
