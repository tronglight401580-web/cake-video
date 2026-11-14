"""Run every regression check and print ONE compact summary table.

    python tools/run_all_tests.py            (takes ~10 min)
Writes the full log to tools/results/tests_<time>.md as well.
"""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def run(args, env=None, timeout=900):
    e = dict(os.environ, **(env or {}))
    t0 = time.perf_counter()
    try:
        p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=e, timeout=timeout)
        out, code = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired as ex:
        out, code = (ex.stdout or "") + "\nTIMEOUT", -1
    lines = [ln for ln in out.splitlines() if not re.match(r"^(W0000|I0000|INFO:|WARNING: Logging)", ln)]
    return code, "\n".join(lines), time.perf_counter() - t0


def nb_frames(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=nb_frames", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return r.stdout.strip()


def main():
    rows, log = [], []

    code, out, dt = run([PY, "tools/test_ui.py"])
    ok = code == 0 and "UI test passed" in out
    key = "; ".join(ln.strip() for ln in out.splitlines() if "->" in ln or "first frame" in ln)[:160]
    rows.append(("UI test", "PASS" if ok else "FAIL", key if ok else out[-600:]))
    log.append(("test_ui", out))

    for clip in ("street_mixed_1227", "asian_hush_48036"):
        code, out, dt = run([PY, "tools/check_yuv_path.py", f"samples/{clip}.mp4"])
        m = re.search(r"mean \|diff\| ([\d.]+), p99 ([\d.]+)", out)
        fps = re.findall(r"(\w+) path: ([\d.]+) fps", out)
        ok = code == 0 and m and float(m.group(1)) < 3.0
        rows.append((f"YUV path {clip}", "PASS" if ok else "FAIL",
                     (", ".join(f"{a} {b} fps" for a, b in fps) + (f"; diff mean {m.group(1)} p99 {m.group(2)}" if m else ""))
                     if ok else out[-600:]))
        log.append((f"yuv {clip}", out))

    tmp = Path(tempfile.mkdtemp(prefix="cake_cli_"))
    for clip in sorted((ROOT / "samples").glob("*.mp4")):
        out_file = tmp / clip.name
        code, out, dt = run([PY, "-m", "cake", "grade", str(clip), "-s", "film_warm", "-o", str(out_file)])
        src, dst = nb_frames(clip), nb_frames(out_file) if out_file.exists() else "-"
        fps = re.search(r"平均 ([\d.]+) fps", out)
        ok = code == 0 and src == dst
        rows.append((f"CLI {clip.stem}", "PASS" if ok else "FAIL",
                     f"frames {src}->{dst}, {fps.group(1) if fps else '?'} fps" if ok else out[-600:]))
        log.append((f"cli {clip.stem}", out))

    code, out, dt = run([PY, "tools/test_seg_gpu.py"])
    fails = re.findall(r"(\S+\.mp4) (\w+ExecutionProvider) (\w+)", out.split("Parity failed:")[-1]) \
        if "Parity failed" in out else []
    expected = {("asian_closeup_v_101040.mp4", "face"), ("asian_closeup_v_101040.mp4", "body"),
                ("neon_night_1230.mp4", "body")}
    got = {(c, k) for c, _, k in fails}
    dml = re.search(r"Dml\w*\s+([\d.]+)", out)
    rows.append(("GPU seg parity", "PASS (known 3)" if got == expected else "CHANGED",
                 f"DML {dml.group(1) if dml else '?'} ms/call; failures {sorted(got)}"))
    log.append(("seg parity", out))

    res = ROOT / "tools" / "results"
    res.mkdir(exist_ok=True)
    f = res / f"tests_{time.strftime('%Y%m%d_%H%M')}.md"
    f.write_text("\n\n".join(f"## {k}\n```\n{v}\n```" for k, v in log), encoding="utf-8")
    print(f"{'check':34s} {'result':16s} detail")
    for name, r, d in rows:
        print(f"{name:34s} {r:16s} {d.splitlines()[0] if d else ''}")
    print(f"\nfull log: {f}")
    sys.exit(0 if all(r.startswith("PASS") for _, r, _ in rows) else 1)


if __name__ == "__main__":
    main()
