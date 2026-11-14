"""Bottleneck benchmark: several configs x clips, with GPU / CPU utilisation sampled during each run.

    python tools/bench_matrix.py          (takes ~10 min)
Prints one table; writes it to tools/results/bench_<time>.md.
"""
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIPS = ["samples/street_mixed_1227.mp4", "samples/asian_hush_48036.mp4"]
CONFIGS = [
    ("base", [], {}),
    ("w2", ["--workers", "2"], {}),
    ("w4", ["--workers", "4"], {}),
    ("segcpu", [], {"CAKE_SEG": "cpu"}),
    ("nullenc", ["--null-encoder"], {}),
    ("noret", ["--retouch", "0"], {}),
]


class Sampler:
    """nvidia-smi (GPU %, NVENC %) + Windows CPU % every 0.5 s while a benchmark runs."""

    def __init__(self):
        self.gpu, self.enc, self.cpu = [], [], []
        self._stop = threading.Event()

    def _gpu_loop(self):
        p = subprocess.Popen(["nvidia-smi", "--query-gpu=utilization.gpu,utilization.encoder",
                              "--format=csv,noheader,nounits", "-lms", "500"],
                             stdout=subprocess.PIPE, text=True)
        while not self._stop.is_set():
            line = p.stdout.readline()
            m = re.match(r"\s*(\d+),\s*(\d+)", line or "")
            if m:
                self.gpu.append(int(m.group(1)))
                self.enc.append(int(m.group(2)))
        p.kill()

    def _cpu_loop(self):
        import ctypes

        class FT(ctypes.Structure):
            _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]

        def times():
            i, k, u = FT(), FT(), FT()
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
            f = lambda t: (t.hi << 32) | t.lo
            return f(i), f(k), f(u)
        prev = times()
        while not self._stop.wait(0.5):
            cur = times()
            idle, kern, user = (c - p for c, p in zip(cur, prev))
            total = kern + user
            if total:
                self.cpu.append(100.0 * (total - idle) / total)
            prev = cur

    def __enter__(self):
        self.threads = [threading.Thread(target=self._gpu_loop, daemon=True),
                        threading.Thread(target=self._cpu_loop, daemon=True)]
        for t in self.threads:
            t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        for t in self.threads:
            t.join(timeout=3)


def stat(xs):
    return f"{statistics.mean(xs):3.0f}/{max(xs):3.0f}" if xs else "  -/  -"


def main():
    rows = []
    for clip in CLIPS:
        for name, args, env in CONFIGS:
            e = dict(os.environ, **env)
            with Sampler() as s:
                p = subprocess.run([sys.executable, "tools/bench_speed.py", clip, *args], cwd=ROOT,
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", env=e, timeout=900)
            m = re.search(r"loop ([\d.]+) fps", p.stdout + p.stderr)
            rows.append((Path(clip).stem, name, m.group(1) if m else "ERR",
                         stat(s.gpu), stat(s.enc), stat(s.cpu)))
            print(*rows[-1], flush=True)
    head = f"{'clip':24s} {'config':8s} {'fps':>6s}  GPU% mean/max  NVENC% mean/max  CPU% mean/max"
    lines = [head] + [f"{c:24s} {n:8s} {f:>6s}  {g:>13s}  {en:>15s}  {cp:>13s}" for c, n, f, g, en, cp in rows]
    res = ROOT / "tools" / "results"
    res.mkdir(exist_ok=True)
    out = res / f"bench_{time.strftime('%Y%m%d_%H%M')}.md"
    out.write_text("```\n" + "\n".join(lines) + "\n```\n", encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
