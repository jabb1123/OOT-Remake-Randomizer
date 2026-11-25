"""Find the dumped files that name a flag or token. Read-only.

Flag names are stored as plain ASCII in the decompressed dumps (the .raw files), so a byte search
finds every file that names a token. Matches are whole names only: "AllSage_IsAfter_Step02" does not
match inside "AllSage_IsAfter_Step02_Exp". Files still zstd-compressed (the .zs dumps) cannot be read
here, so they are listed as skipped. Use their .raw copy instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "tmp" / "Events" / "raw"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
TOKEN_RE = re.compile(r"[A-Za-z0-9_.]+")

# (token, file stem) -> (class, note). Empty until hits are reviewed by hand.
REVIEWED: dict[tuple[str, str], tuple[str, str]] = {}


@dataclass(frozen=True)
class Hit:
    path: str
    kind: str
    review: str
    note: str


@dataclass
class Result:
    hits: list[Hit] = field(default_factory=list)
    skipped_compressed: list[str] = field(default_factory=list)
    scanned: int = 0


def _kind(name: str) -> str:
    if ".bfevfl" in name:
        return "event flow"
    if ".ainb" in name:
        return "logic module"
    if ".gyml" in name or ".byml" in name:
        return "data"
    return "other"


def find_consumers(root: Path, token: str, suffixes: tuple[str, ...] | None = None) -> Result:
    """Scan every file under `root` for `token`. `suffixes` limits the files by extension, e.g. ("raw",)."""
    if not TOKEN_RE.fullmatch(token):
        raise ValueError(f"not a flag or token name: {token!r}")
    pattern = re.compile(rb"(?<![A-Za-z0-9_])" + re.escape(token.encode("ascii")) + rb"(?![A-Za-z0-9_])")
    result = Result()
    for file in sorted(p for p in root.rglob("*") if p.is_file()):
        if suffixes and file.suffix.lstrip(".") not in suffixes:
            continue
        rel = file.relative_to(root).as_posix()
        data = file.read_bytes()
        if data.startswith(ZSTD_MAGIC):
            result.skipped_compressed.append(rel)
            continue
        result.scanned += 1
        if not pattern.search(data):
            continue
        stem = file.name.split(".")[0]
        review, note = REVIEWED.get((token, stem), ("unreviewed", ""))
        result.hits.append(Hit(path=rel, kind=_kind(file.name), review=review, note=note))
    return result


def format_result(token: str, root: Path, result: Result) -> str:
    lines = [f"Files naming {token} under {root}:"]
    for hit in result.hits:
        note = f" - {hit.note}" if hit.note else ""
        lines.append(f"  [{hit.kind}] {hit.path} ({hit.review}){note}")
    if not result.hits:
        lines.append("  (none)")
    lines.append(f"{len(result.hits)} hit(s) in {result.scanned} scanned file(s)")
    if result.skipped_compressed:
        lines.append(f"{len(result.skipped_compressed)} zstd-compressed file(s) skipped; their .raw copies are scanned")
    return "\n".join(lines)
