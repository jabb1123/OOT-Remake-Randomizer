"""Export the RomFS files a randomized NUP changed as a loose-file mod folder.

Eden (Lichii) loads a RomFS mod from `load/<TitleID>/<mod>/romfs/`, with each file at
the path it has inside the game's RomFS. Only files that are new or whose stored bytes
differ from the source are written, so the mod is much smaller than a ROM copy.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterator

from nup import format as F
from nup.access import iter_children
from nup.read import NupReader


def _romfs_files(r: NupReader, dir_index: int, prefix: str = "") -> Iterator[tuple[str, int]]:
    for ref in iter_children(r, dir_index):
        name = ref.name.decode(errors="replace")
        if ref.is_dir:
            yield from _romfs_files(r, ref.index, f"{prefix}{name}/")
        else:
            yield f"{prefix}{name}", ref.index


def _romfs_index(r: NupReader) -> dict[str, int]:
    """Map romfs path to file index. A path present in several packages keeps its first copy."""
    index: dict[str, int] = {}
    for pkg in r.packages:
        if pkg.romfs_dir == F.NO_DIR:
            continue
        for path, idx in _romfs_files(r, pkg.romfs_dir):
            index.setdefault(path, idx)
    return index


def changed_romfs_files(source: Path, patched: Path) -> dict[str, bytes]:
    """Map romfs path to content for every file that is new or whose stored bytes differ."""
    changed: dict[str, bytes] = {}
    with NupReader(str(source)) as src, NupReader(str(patched)) as out:
        src_index = _romfs_index(src)
        for path, idx in _romfs_index(out).items():
            new_info = out.file_info(idx)
            if path in src_index:
                old_info = src.file_info(src_index[path])
                # The TOC sha256 covers the stored bytes, so equal size and hash means unchanged.
                if old_info[1:3] == new_info[1:3]:
                    continue
            changed[path] = out.read_file(idx)
    return changed


def export_mod(source: Path, patched: Path, mod_dir: Path) -> int:
    """Write the files that differ between `source` and `patched` under `mod_dir/romfs`.

    Returns the number of files written. Only the `romfs` folder under `mod_dir` is replaced.
    """
    changed = changed_romfs_files(source, patched)
    romfs_root = mod_dir / "romfs"
    shutil.rmtree(romfs_root, ignore_errors=True)
    for path, data in changed.items():
        target = romfs_root.joinpath(*path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return len(changed)
