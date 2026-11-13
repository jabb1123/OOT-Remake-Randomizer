# Suggested Commands

```bash
# Activate venv (always needed first)
source /Users/jacob/Desktop/Roms/oot_randomizer/.venv/bin/activate
cd /Users/jacob/Desktop/Roms/oot_randomizer

# Run all tests
PYTHONPATH=src python -m unittest discover -s tests -v

# Scan NUP structure (no copy made, read-only)
oot-randomizer scan --rom "/Users/jacob/Desktop/Roms/The Legend of Zelda Ocarina of Time + U2/The Legend of Zelda Ocarina of Time   U2.0.0.nup" --max-mb 256 --json-out nup_scan.json

# Generate a randomized ROM copy (safe — never touches original)
oot-randomizer randomize --rom "...file.nup" --seed 12345 --output /path/to/output.nup

# Install nup reference library (needed if venv is fresh)
git clone --depth=1 https://github.com/a55uka/nup.git /tmp/nup_ref
pip install /tmp/nup_ref/tools/nup
```
