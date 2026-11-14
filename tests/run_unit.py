"""Minimal pytest-style test runner for environments without pytest."""
import importlib.util
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
failures = 0
count = 0
for path in sorted(Path(__file__).parent.glob('test_*.py')):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, fn in sorted(vars(module).items()):
        if name.startswith('test_') and callable(fn):
            count += 1
            try:
                fn()
                print(f'PASS {path.name}::{name}')
            except Exception:
                failures += 1
                print(f'FAIL {path.name}::{name}')
                traceback.print_exc()
print(f'{count - failures}/{count} passed')
sys.exit(bool(failures))
