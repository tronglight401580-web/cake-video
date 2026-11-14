"""Export selected decoded video frames as lossless PNGs."""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cake.media import target_size
from cake.pipeline import _grab_frame, _to_u8
from cake.probe import probe


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("clip")
    ap.add_argument("--times", required=True, help="comma-separated seconds")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--max-short", type=int, default=None)
    ap.add_argument("--tonemap", default="mobius")
    args = ap.parse_args()
    times = [float(t) for t in args.times.split(",")]
    if not times or any(t < 0 for t in times):
        ap.error("times must be non-negative seconds")
    info = probe(args.clip)
    w, h = target_size(info, args.max_short)
    hb = info.high_bit or bool(info.hdr)
    from PIL import Image
    args.out.mkdir(parents=True, exist_ok=True)
    for t in times:
        frame = _grab_frame(info, t, w, h, hb, args.tonemap)
        image = _to_u8(frame, w, h, hb)
        dest = args.out / f"{Path(args.clip).stem}_{t:g}s.png"
        Image.fromarray(image, "RGB").save(dest, format="PNG")
        print(dest)


if __name__ == "__main__":
    main()
