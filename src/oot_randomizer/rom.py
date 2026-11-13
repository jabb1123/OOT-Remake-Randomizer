from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class RomValidationError(ValueError):
    """Raised when an input ROM file is invalid or not suitable for randomization."""


@dataclass(slots=True)
class RomInfo:
    path: Path
    file_name: str
    size_bytes: int
    is_nup: bool
    likely_target: str


def validate_nup_rom(path: str | Path) -> RomInfo:
    """Validate the input ROM file and return a small summary object.

    This project treats `.nup` files as the expected source input. The actual
    patching logic is deliberately left for later phases, but validation is done
    early so the rest of the pipeline can assume a usable file.
    """
    rom_path = Path(path)

    if not rom_path.exists():
        raise FileNotFoundError(f"ROM file does not exist: {rom_path}")

    if not rom_path.is_file():
        raise RomValidationError(f"ROM path is not a file: {rom_path}")

    if rom_path.suffix.lower() != ".nup":
        raise RomValidationError(
            f"Unsupported ROM format: {rom_path.suffix or '<none>'}. Expected .nup."
        )

    size_bytes = rom_path.stat().st_size
    if size_bytes <= 0:
        raise RomValidationError(f"ROM file is empty: {rom_path}")

    file_name = rom_path.name.lower()
    likely_target = "ocarina_of_time" if "oot" in file_name or "zelda" in file_name else "unknown"

    return RomInfo(
        path=rom_path,
        file_name=rom_path.name,
        size_bytes=size_bytes,
        is_nup=True,
        likely_target=likely_target,
    )
