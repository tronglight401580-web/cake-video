#!/usr/bin/env python3
"""Measure temporal flicker added by video processing, with face-focused metrics."""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw


METRICS = ("face_shimmer", "face_breathing", "frame_shimmer", "frame_breathing")


def probe(path: Path) -> dict:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
           "stream=width,height,avg_frame_rate,r_frame_rate", "-of", "json", str(path)]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8")
    streams = json.loads(result.stdout).get("streams", [])
    if not streams:
        raise ValueError(f"No video stream found: {path}")
    s = streams[0]
    return {"width": int(s["width"]), "height": int(s["height"]),
            "fps": s.get("avg_frame_rate", s.get("r_frame_rate", "0/1"))}


def output_size(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, 1080.0 / min(width, height))
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def frame_stream(path: Path, width: int, height: int, limit: int):
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-an", "-sn", "-dn",
           "-vf", f"scale={width}:{height}:flags=lanczos", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    frame_bytes = width * height * 3
    try:
        for _ in range(limit):
            data = bytearray()
            while len(data) < frame_bytes:
                chunk = proc.stdout.read(frame_bytes - len(data))
                if not chunk:
                    break
                data.extend(chunk)
            if len(data) != frame_bytes:
                break
            yield np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
    finally:
        proc.stdout.close()
        if proc.poll() is None:
            proc.terminate()
        stderr = proc.stderr.read() if proc.stderr else b""
        code = proc.wait()
        if code not in (0, -15) and stderr:
            raise RuntimeError(f"ffmpeg failed for {path}: {stderr.decode(errors='replace')}")


def make_landmarker(model_path: Path):
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    options = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=10,
    )
    return vision.FaceLandmarker.create_from_options(options)


def face_mask(rgb: np.ndarray, landmarker) -> np.ndarray:
    import mediapipe as mp

    h, w = rgb.shape[:2]
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    result = landmarker.detect(mp_image)
    mask = np.zeros((h, w), dtype=np.uint8)
    for landmarks in result.face_landmarks:
        points = np.array([[int(round(p.x * (w - 1))), int(round(p.y * (h - 1)))]
                           for p in landmarks], dtype=np.int32)
        hull = cv2.convexHull(points)
        cv2.fillConvexPoly(mask, hull, 1)
    return mask.astype(bool)


def summarize(values: list[float | None]) -> dict:
    valid = np.asarray([v for v in values if v is not None], dtype=np.float64)
    if not valid.size:
        return {"mean": None, "p95": None, "max": None}
    return {"mean": float(valid.mean()), "p95": float(np.percentile(valid, 95)), "max": float(valid.max())}


def draw_chart(records: list[dict], heat: np.ndarray, path: Path) -> None:
    width, height = 1000, 660
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    colors = {"face_shimmer": (220, 50, 47), "face_breathing": (38, 139, 210),
              "frame_shimmer": (133, 153, 0), "frame_breathing": (181, 137, 0)}
    left, top, right, bottom = 65, 45, 965, 475
    d.rectangle((left, top, right, bottom), outline=(80, 80, 80))
    values = [r[k] for r in records for k in METRICS if r[k] is not None]
    ymax = max(1.0, float(max(values)) if values else 1.0)
    ymax = math.ceil(ymax * 1.1 * 2) / 2
    for i in range(5):
        y = bottom - (bottom - top) * i / 4
        d.line((left, y, right, y), fill=(225, 225, 225))
        d.text((12, y - 7), f"{ymax * i / 4:.1f}", fill=(50, 50, 50))
    d.text((left, 15), "Added flicker (8-bit luma levels)", fill=(30, 30, 30))
    n = len(records)
    for key, color in colors.items():
        pts = []
        for i, rec in enumerate(records):
            value = rec[key]
            if value is None:
                if len(pts) > 1:
                    d.line(pts, fill=color, width=2)
                pts = []
                continue
            x = left + (right - left) * (i / max(1, n - 1))
            y = bottom - (bottom - top) * min(float(value), ymax) / ymax
            pts.append((x, y))
        if len(pts) > 1:
            d.line(pts, fill=color, width=2)
    legend_x = left
    for key, color in colors.items():
        d.line((legend_x, 500, legend_x + 22, 500), fill=color, width=3)
        d.text((legend_x + 28, 493), key, fill=(30, 30, 30))
        legend_x += 220
    hm = np.clip(heat, 0, 30) / 30.0
    rgb = np.stack((np.clip(hm * 2, 0, 1), np.clip(2 - np.abs(hm * 2 - 1) * 2, 0, 1), np.clip(1 - hm * 2, 0, 1)), axis=-1)
    thumb = Image.fromarray(np.uint8(rgb * 255)).convert("RGB")
    thumb.thumbnail((400, 135))
    x0, y0 = (width - thumb.width) // 2, 530
    img.paste(thumb, (x0, y0))
    d.text((x0, y0 - 18), "Mean added-flicker map (0–30 levels)", fill=(30, 30, 30))
    img.save(path)


def analyze(original: Path, processed: Path, out_dir: Path, max_frames: int) -> dict:
    oi, pi = probe(original), probe(processed)
    w, h = output_size(oi["width"], oi["height"])
    model = Path(__file__).resolve().parent.parent / "models" / "face_landmarker.task"
    if not model.is_file():
        raise FileNotFoundError(f"FaceLandmarker model not found: {model}")
    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    heat_sum = np.zeros((h, w), dtype=np.float64)
    pair_count = 0
    frames_with_face = 0
    # MediaPipe's native loader cannot open non-ASCII Windows paths on some builds.
    with tempfile.TemporaryDirectory(prefix="flicker-model-") as model_temp:
        local_model = Path(model_temp) / "face_landmarker.task"
        shutil.copyfile(model, local_model)
        with make_landmarker(local_model) as landmarker:
            orig_iter = frame_stream(original, w, h, max_frames)
            proc_iter = frame_stream(processed, w, h, max_frames)
            previous_o = next(orig_iter, None)
            previous_p = next(proc_iter, None)
            t = 1
            while previous_o is not None and previous_p is not None:
                curr_o, curr_p = next(orig_iter, None), next(proc_iter, None)
                if curr_o is None or curr_p is None:
                    break
                y_o = (0.2126 * previous_o[..., 0] + 0.7152 * previous_o[..., 1] + 0.0722 * previous_o[..., 2])
                y_ot = (0.2126 * curr_o[..., 0] + 0.7152 * curr_o[..., 1] + 0.0722 * curr_o[..., 2])
                y_p = (0.2126 * previous_p[..., 0] + 0.7152 * previous_p[..., 1] + 0.0722 * previous_p[..., 2])
                y_pt = (0.2126 * curr_p[..., 0] + 0.7152 * curr_p[..., 1] + 0.0722 * curr_p[..., 2])
                delta = (y_pt - y_p) - (y_ot - y_o)
                shimmer = np.abs(delta)
                breathing_map = np.abs(cv2.GaussianBlur(delta.astype(np.float32), (0, 0), sigmaX=4, sigmaY=4))
                mask = face_mask(curr_o, landmarker)
                has_face = bool(mask.any())
                if has_face:
                    frames_with_face += 1
                rec = {"frame": t}
                for key, values in (("shimmer", shimmer), ("breathing", breathing_map)):
                    rec["frame_" + key] = float(values.mean())
                    rec["face_" + key] = float(values[mask].mean()) if has_face else None
                records.append(rec)
                heat_sum += shimmer
                pair_count += 1
                previous_o, previous_p = curr_o, curr_p
                t += 1
    heat = heat_sum / max(1, pair_count)
    summary = {key: summarize([r[key] for r in records]) for key in METRICS}
    payload = {"original": str(original), "processed": str(processed), "width": w, "height": h,
               "fps": oi["fps"], "frames_analyzed": pair_count + (1 if pair_count else 0),
               "frames_with_face": frames_with_face, "metrics": METRICS,
               "per_frame": records, "summary": summary}
    stem = processed.stem
    json_path = out_dir / f"{stem}_flicker.json"
    png_path = out_dir / f"{stem}_flicker.png"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    draw_chart(records, heat, png_path)
    print(f"Flicker metrics for {processed.name} (8-bit levels; {pair_count} frame transitions)")
    print(f"{'metric':<18} {'mean':>10} {'p95':>10} {'max':>10}")
    for key in METRICS:
        s = summary[key]
        fmt = lambda v: "n/a" if v is None else f"{v:.3f}"
        print(f"{key:<18} {fmt(s['mean']):>10} {fmt(s['p95']):>10} {fmt(s['max']):>10}")
    print(f"Frames with face: {frames_with_face}; wrote {json_path} and {png_path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("processed", type=Path)
    parser.add_argument("--max-frames", type=int, default=240)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.max_frames < 2:
        parser.error("--max-frames must be at least 2")
    out = args.out or args.processed.parent / "flicker"
    try:
        analyze(args.original, args.processed, out, args.max_frames)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"flicker: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
