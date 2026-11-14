# Task: run two scripts and relay their summaries (you are a test runner)

Do NOT edit any existing file. Do not fix anything. No network, no pip install.
Working directory: `D:\像素蛋糕视频版`. Run the two commands ONE AFTER THE OTHER (not in parallel),
each in the foreground, and wait for it to finish — each takes about 10 minutes. Use a generous
command timeout (at least 1200 seconds). If your shell tool times out, re-run that same command with
a longer timeout; do not try to split it up.

1. `python tools/run_all_tests.py`
2. `python tools/bench_matrix.py`

Each prints a summary table at the end and writes a file under `tools/results/`.

## Final message
Copy BOTH final summary tables verbatim (no rewording), plus the two result-file paths.
If a script crashed, give its last 20 lines instead. Nothing else.
