# Tech Stack

- **Language**: Python 3.11+ (tested on 3.13.1)
- **Venv**: `.venv/` in project root — always activate before running
- **Build**: setuptools + pyproject.toml; editable install via `pip install -e .`
- **CLI entrypoint**: `oot-randomizer` (registered as script)
- **Key deps** (installed in venv):
  - `zstandard` — ZSTD compression/decompression with dictionary support
  - `nup` (from `a55uka/nup` `tools/nup/`) — NUP container read/extract
  - `oead` — Nintendo binary format helpers (SARC etc.)
  - `lz4` — installed but not used for game files (ZBIC ≠ LZ4)
  - `zstandard` — required; ZsDic.pack uses dict IDs 1–4
- **No runtime deps declared** in pyproject.toml — deps are manually installed
