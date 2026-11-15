# Regression run on main after merging stream A (2bbe985)

Run only; do NOT edit any source, test or doc file (outputs under `tools/results/` are fine).
Run each command from the repo root, in this order, and record pass/fail plus the key numbers:

1. `python tests/run_unit.py`
2. `python tools/golden.py check`
3. `python tools/run_all_tests.py`
4. `python tools/test_refcolor.py`
5. `python tools/test_b.py`
6. `python tools/test_pershot.py`
7. `python tools/test_ui.py`
8. `python tools/test_a.py` - KNOWN: its "fade-free frames" stability check fails by design of the
   criterion (every frame counts as fading); report it but do not treat it as a regression. Every
   other check in it must pass.
9. `python tools/bench_speed.py` - report fps for each configuration and compare with the most
   recent `tools/results/bench_*.md` (flag any drop > 10%).

If anything fails, re-run it once to rule out flakiness, then report the failing output lines
(<= 10 per failure). Do not try to fix anything. Report < 30 lines.
