"""Throughput benchmark for the full grade pipeline (needs a __main__ guard: worker processes).

    python tools/bench_speed.py CLIP [--retouch 0.5] [--seg-every 2] [--workers 3] [--null-encoder]
"""
import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class NullEnc:
    def __init__(self, *a, **k):
        pass

    def write(self, b):
        pass

    def close(self):
        return 0, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--style", default="film_warm")
    ap.add_argument("--retouch", type=float, default=0.5)
    ap.add_argument("--seg-every", type=int, default=2)
    ap.add_argument("--workers", type=int)
    ap.add_argument("--null-encoder", action="store_true")
    ap.add_argument("--duration", type=float)
    a = ap.parse_args()

    import cake.face as F
    import cake.pipeline as P
    from cake.styles import load_style
    orig = F.Analyzer.__init__

    def init(self, *args, **kw):
        kw["seg_every"] = a.seg_every
        if a.workers:
            kw["workers"] = a.workers
        orig(self, *args, **kw)
    F.Analyzer.__init__ = init
    if a.null_encoder:
        P.Encoder = NullEnc
    out = os.path.join(tempfile.gettempdir(), "cake_bench.mp4")
    st = load_style(a.style)
    t0 = time.perf_counter()
    s = P.grade_video(a.clip, out, st, retouch=a.retouch, log=lambda *x: None, duration=a.duration)
    wall = time.perf_counter() - t0
    print(f"{Path(a.clip).name}: {s['frames']} frames, loop {s['fps']:.1f} fps, "
          f"wall {s['frames'] / wall:.1f} fps (incl. startup {wall - s['seconds']:.1f}s) "
          f"[seg={os.environ.get('CAKE_SEG', 'auto')} analyzer={os.environ.get('CAKE_ANALYZER', 'process')} "
          f"seg_every={a.seg_every} null_enc={a.null_encoder}]")


if __name__ == "__main__":
    main()
