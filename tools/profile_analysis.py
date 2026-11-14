"""Analysis-only throughput: is the process pool limited by compute, IPC or the GPU?

    python tools/profile_analysis.py CLIP
"""
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    import cake.face as F
    from cake.media import Decoder, target_size
    from cake.probe import probe
    clip = sys.argv[1]
    info = probe(clip)
    w, h = target_size(info, 1080)
    t = time.perf_counter()
    frames = list(Decoder(info, w, h, False, frames=150))
    print(f"decode 150 frames: {(time.perf_counter() - t) / 150 * 1000:.1f} ms/frame")
    t = time.perf_counter()
    smalls = [F.to_small(f, w, h, False) for f in frames]
    print(f"to_small: {(time.perf_counter() - t) / 150 * 1000:.1f} ms/frame")
    raw = F.run_models(smalls[0], True, 0)
    t = time.perf_counter()
    for _ in range(50):
        pickle.loads(pickle.dumps(smalls[0])), pickle.loads(pickle.dumps(raw))
    print(f"pickle round-trip (frame + result): {(time.perf_counter() - t) / 50 * 1000:.1f} ms; "
          f"payload {len(pickle.dumps(smalls[0])) / 1e6:.2f} MB + {len(pickle.dumps(raw)) / 1e6:.2f} MB")

    for workers in (1, 2, 3, 4):
        a = F.Analyzer(workers=workers, fps=float(info.fps))
        a.wait_ready()
        a.reset()
        t = time.perf_counter()
        for i, f in enumerate(frames):
            a.submit(f, w, h, False, i)
        a.finish()
        for i in range(len(frames)):
            a.result(i)
        dt = time.perf_counter() - t
        a.close()
        print(f"process pool, {workers} workers: {len(frames) / dt:.1f} frames/s (analysis only)")


if __name__ == "__main__":
    main()
