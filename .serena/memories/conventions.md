# Code Conventions

- One-line comments only where non-obvious; no docstrings on simple methods
- `dataclass(slots=True)` for all data records
- `RomValidationError(ValueError)` for all user-facing input errors
- Patcher is always non-destructive: `shutil.copy2` then patch the copy
- `PatchRecord.byte_offset = None` → manifest-only mode (safe default)
- BYML offsets are tracked at the BYML binary level, not via re-serialization
- ZSTD dict_id is detected from the ZSTD frame header at runtime (never hardcoded)
- NUP TOC `size` == `extent_size` for codec=raw; both must be updated on patch
- 16-byte alignment required for all NUP extent offsets
- Tests live in `tests/`; run with `PYTHONPATH=src`
