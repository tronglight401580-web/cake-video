# Stream A check 7: run only

Run only; do NOT edit any file (outputs under `tools/results/` are fine). The product owner changed
the stability criterion in `tools/test_a.py` (see the 2026-11-14 comments: acceleration + 15-frame
high-pass on the warp field are pass/fail; raw step p95 and detector-based checks are report-only).

Run from this directory: `python tests/run_unit.py`, `python tools/golden.py check`,
`python tools/test_a.py`, `python tools/test_b.py`, `python tools/test_ui.py`.
Report < 20 lines: pass/fail of each, and from test_a the onset ratios + yaw, the field high-pass
std and accel p95 for every clip/setting/face, and any remaining failure lines verbatim.
