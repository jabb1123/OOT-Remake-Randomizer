# Task Completion

After any code change:

```bash
cd /Users/jacob/Desktop/Roms/oot_randomizer
source .venv/bin/activate
PYTHONPATH=src python -m unittest discover -s tests -v
```

Expected: `Ran 30 tests in ~0.01s — OK`

No linter/formatter configured. No type checker configured.
