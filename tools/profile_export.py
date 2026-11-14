"""Where does export time go? Main-thread breakdown + per-worker breakdown (process mode).

    python tools/profile_export.py CLIP
"""
import collections
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def worker_profile(small, n=40):
    """Run the worker steps in this process to see their individual cost."""
    import cake.face as F
    F._models()
    F._gpu_segmenter()
    T = collections.defaultdict(float)
    for i in range(n):
        t = time.perf_counter()
        seg = F._segment(small, F._tls.seg) if i % 2 == 0 else None
        T["segment (every 2nd frame)"] += time.perf_counter() - t
        import mediapipe as mp
        t = time.perf_counter()
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=small)
        F._tls.ts += 40
        res = F._tls.lmk.detect_for_video(img, F._tls.ts)
        T["landmarks (VIDEO mode)"] += time.perf_counter() - t
        t = time.perf_counter()
        h, w = small.shape[:2]
        faces = [__import__("numpy").array([[q.x * w, q.y * h] for q in p], "f4") for p in res.face_landmarks]
        F.landmark_layers(faces, (h, w))
        T["landmark layers"] += time.perf_counter() - t
    return {k: v / n * 1000 for k, v in T.items()}


def main():
    clip = sys.argv[1]
    import numpy as np
    import cake.face as F
    import cake.gpu as G
    import cake.pipeline as P
    from cake.media import Decoder, target_size
    from cake.probe import probe
    from cake.styles import load_style

    info = probe(clip)
    w, h = target_size(info, 1080)
    dec = Decoder(info, w, h, False, frames=1)
    frame = next(iter(dec))
    dec.close()
    small = F.to_small(frame, w, h, False)
    print("worker steps (ms/frame, single process):")
    for k, v in worker_profile(small).items():
        print(f"  {k:28s} {v:6.1f}")

    T = collections.defaultdict(float)

    def wrap(cls, name, key):
        f = getattr(cls, name)

        def g(*a, **k):
            t = time.perf_counter()
            r = f(*a, **k)
            T[key] += time.perf_counter() - t
            return r
        setattr(cls, name, g)
    wrap(F.Analyzer, "result", "wait for analysis")
    wrap(G.Renderer, "set_face", "set_face (upload+mask)")
    wrap(G.Renderer, "render", "render (GPU + readback)")
    out = os.path.join(tempfile.gettempdir(), "cake_prof.mp4")
    s = P.grade_video(clip, out, load_style("film_warm"), retouch=0.5, log=lambda *a: None)
    n = s["frames"]
    print(f"\nexport: {s['fps']:.1f} fps = {1000 / s['fps']:.1f} ms/frame (main thread):")
    for k, v in T.items():
        print(f"  {k:28s} {v / n * 1000:6.1f}")
    other = 1000 / s["fps"] - sum(v / n * 1000 for v in T.values())
    print(f"  {'other (queues, encode wait)':28s} {other:6.1f}")


if __name__ == "__main__":
    main()
