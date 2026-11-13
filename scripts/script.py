
from pathlib import Path
from shutil import copy2
from nup.read import NupReader
from nup.access import iter_children
from oot_randomizer.nup_chest_patcher import NupChestPatcher

nup_src = Path('/Users/jacob/Desktop/Roms/The Legend of Zelda Ocarina of Time + U2/The Legend of Zelda Ocarina of Time   U2.0.0.nup')
zsdic = Path('/Users/jacob/Desktop/Roms/oot_randomizer/ZsDic.pack')
out = Path('/tmp/oot_nup_patch_probe.nup')
copy2(nup_src, out)
patcher = NupChestPatcher(out, zsdic.read_bytes())

r = NupReader(str(nup_src))
for pkg in r.packages:
    def walk(dir_index, prefix=''):
        for ref in iter_children(r, dir_index):
            if ref.is_dir:
                yield from walk(ref.index, prefix + '/' + ref.name.decode(errors='replace'))
            else:
                nm = prefix + '/' + ref.name.decode(errors='replace')
                if nm.lower().endswith('.bcett.byml.zs'):
                    yield nm.lstrip('/')
    for name in walk(pkg.romfs_dir):
        try:
            chests = patcher.scan_chests(name, pkg_index=pkg.index)
        except Exception:
            continue
        if chests:
            result = patcher.patch_scene(name, {chests[0].vanilla_drop: 'Item_Range_Bow'}, target_replacements=[{
                'room_index': chests[0].room_index,
                'check_index': 0,
                'vanilla_item': chests[0].vanilla_drop,
                'replacement_item': 'Item_Range_Bow',
            }], pkg_index=pkg.index)
            print('scene', name)
            print('found', len(chests), 'patched', result.chests_patched)
            print('swap', chests[0].vanilla_drop, '->', 'Item_Range_Bow')
            break
    else:
        continue
    break
else:
    raise SystemExit('no chest file found')