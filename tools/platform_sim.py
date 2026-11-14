#!/usr/bin/env python3
"""Simulate short-video platform H.264 compression and inspect grain survival."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def run(args: list[str], *, stdout=None) -> subprocess.CompletedProcess:
    return subprocess.run(args, stdout=subprocess.PIPE if stdout is None else stdout,
                          stderr=subprocess.PIPE, check=True)


def probe(path: Path) -> tuple[int, int, float]:
    result = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                  "stream=width,height,duration:format=duration", "-of", "json", str(path)])
    data = json.loads(result.stdout.decode("utf-8"))
    stream = data["streams"][0]
    duration = float(stream.get("duration") or data["format"]["duration"])
    return int(stream["width"]), int(stream["height"]), duration


def bitrate_value(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kKmM]?)\s*", value)
    if not match:
        raise argparse.ArgumentTypeError(f"invalid bitrate: {value}")
    number, suffix = match.groups()
    multiplier = {"": 1, "k": 1_000, "m": 1_000_000}[suffix.lower()]
    return int(float(number) * multiplier)


def bitrate_label(value: int) -> str:
    if value >= 1_000_000:
        amount = value / 1_000_000
        return f"{amount:g}M"
    if value % 1_000 == 0:
        return f"{value // 1_000}k"
    return str(value)


def fit_size(width: int, height: int, max_width: int = 1080, max_height: int = 1920) -> tuple[int, int]:
    scale = min(1.0, max_width / width, max_height / height)
    # yuv420p requires even dimensions.
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def gaussian_kernel(sigma: float) -> np.ndarray:
    radius = int(math.ceil(3 * sigma))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-(x * x) / (2 * sigma * sigma))
    return kernel / kernel.sum()


def convolve_axis(image: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    radius = len(kernel) // 2
    padded = np.pad(image, [(radius, radius) if i == axis else (0, 0) for i in range(2)], mode="reflect")
    return sum(float(weight) * np.take(padded, range(i, i + image.shape[axis]), axis=axis)
               for i, weight in enumerate(kernel))


def box_mean(image: np.ndarray, size: int) -> np.ndarray:
    radius = size // 2
    padded = np.pad(image, ((radius, radius), (radius, radius)), mode="reflect")
    integral = np.pad(padded, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    sums = integral[size:, size:] - integral[:-size, size:] - integral[size:, :-size] + integral[:-size, :-size]
    return sums / (size * size)


def luma(rgb: np.ndarray) -> np.ndarray:
    rgb = rgb.astype(np.float64)
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def metric_image(rgb: np.ndarray) -> tuple[dict[str, float], np.ndarray, np.ndarray]:
    y = luma(rgb)
    kernel = gaussian_kernel(1.5)
    blurred = convolve_axis(convolve_axis(y, kernel, 0), kernel, 1)
    residual = np.abs(y - blurred)
    mean = box_mean(blurred, 7)
    variance = np.maximum(0.0, box_mean(blurred * blurred, 7) - mean * mean)
    local_std = np.sqrt(variance)
    threshold = float(np.percentile(local_std, 30))
    flat = local_std <= threshold
    hf_flat = float(residual[flat].mean()) if flat.any() else 0.0
    hf = float(residual.mean())

    # A run of six or more zero second differences is a simple proxy for a visible
    # flat tonal plateau; it is not a perceptual or codec-specific banding detector.
    second = np.diff(y, n=2, axis=1)
    zero = np.abs(second) < 1e-9
    run_mask = np.zeros_like(zero, dtype=bool)
    for start in range(max(0, zero.shape[1] - 5)):
        block = zero[:, start:start + 6]
        run_mask[:, start:start + 6] |= np.all(block, axis=1)[:, None]
    corresponding_flat = flat[:, 1:-1]
    banding = float(np.count_nonzero(run_mask & corresponding_flat) / max(1, np.count_nonzero(corresponding_flat)))
    return {"hf": hf, "hf_flat": hf_flat, "banding": banding}, flat, local_std


def extract_frame(path: Path, seconds: float) -> np.ndarray:
    width, height, _ = probe(path)
    result = run(["ffmpeg", "-v", "error", "-ss", f"{seconds:.6f}", "-i", str(path), "-frames:v", "1",
                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    expected = width * height * 3
    if len(result.stdout) != expected:
        raise RuntimeError(f"could not extract a full frame from {path} at {seconds}s")
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(height, width, 3).copy()


def resize_rgb(frame: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    if (frame.shape[1], frame.shape[0]) == size:
        return frame
    return np.asarray(Image.fromarray(frame).resize(size, Image.Resampling.LANCZOS))


def flat_crop(frame: np.ndarray, local_std: np.ndarray, side: int = 320) -> np.ndarray:
    h, w = local_std.shape
    side = min(side, h, w)
    integral = np.pad(local_std, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    sums = integral[side:, side:] - integral[:-side, side:] - integral[side:, :-side] + integral[:-side, :-side]
    cy, cx = np.unravel_index(np.argmin(sums), sums.shape)
    return frame[cy:cy + side, cx:cx + side]


def make_contact_sheet(rows: list[list[dict]], labels: list[str], path: Path) -> None:
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    try:
        font = ImageFont.truetype(str(font_path), 16) if font_path.exists() else ImageFont.load_default()
    except OSError:
        font = ImageFont.load_default()
    cell_w, thumb_h, crop_side, label_h = 360, 640, 320, 48
    row_h = thumb_h + crop_side + label_h
    sheet = Image.new("RGB", (cell_w * len(labels), row_h * len(rows)), "#171717")
    draw = ImageDraw.Draw(sheet)
    for ri, row in enumerate(rows):
        for ci, entry in enumerate(row):
            x, y = ci * cell_w, ri * row_h
            image = Image.fromarray(entry["frame"])
            scale = cell_w / image.width
            thumb = image.resize((cell_w, max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
            if thumb.height > thumb_h:
                top = (thumb.height - thumb_h) // 2
                thumb = thumb.crop((0, top, cell_w, top + thumb_h))
            sheet.paste(thumb, (x, y))
            crop = Image.fromarray(entry["crop"])
            sheet.paste(crop.resize((crop_side, crop_side), Image.Resampling.LANCZOS), (x + (cell_w - crop_side) // 2, y + thumb_h))
            retention = "" if entry["retention"] is None else f"  retention {entry['retention']:.3f}"
            draw.text((x + 6, y + thumb_h + crop_side + 8), f"{labels[ci]}{retention}", fill="white", font=font)
    sheet.save(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graded", type=Path)
    parser.add_argument("--orig", type=Path)
    parser.add_argument("--times", help="comma-separated seconds; defaults to 10%, 50%, 90%")
    parser.add_argument("--bitrates", default="3M,1.5M")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    graded = args.graded.resolve()
    out = args.out.resolve() if args.out else graded.parent / "sim"
    out.mkdir(parents=True, exist_ok=True)
    gw, gh, duration = probe(graded)
    times = [float(t) for t in args.times.split(",")] if args.times else [duration * p for p in (0.1, 0.5, 0.9)]
    if any(t < 0 or t >= duration for t in times):
        parser.error(f"sample times must be within the video duration ({duration:.3f}s)")
    bitrates = [bitrate_value(v) for v in args.bitrates.split(",")]
    width, height = fit_size(gw, gh)
    encoded: list[tuple[str, Path]] = []
    for bps in bitrates:
        label = bitrate_label(bps)
        destination = out / f"{graded.stem}_{label}.mp4"
        if not destination.exists() or destination.stat().st_mtime < graded.stat().st_mtime:
            run(["ffmpeg", "-y", "-v", "error", "-i", str(graded), "-vf", f"scale={width}:{height}:flags=lanczos",
                 "-c:v", "libx264", "-preset", "veryfast", "-b:v", str(bps), "-maxrate", str(int(bps * 1.5)),
                 "-bufsize", str(bps * 2), "-profile:v", "high", "-pix_fmt", "yuv420p", "-an", str(destination)])
        encoded.append((label, destination))

    versions: list[tuple[str, Path, bool]] = []
    if args.orig:
        versions.append(("orig", args.orig.resolve(), False))
    versions.append(("graded", graded, True))
    versions.extend((label, path, False) for label, path in encoded)
    report: dict = {"graded": str(graded), "original": str(args.orig.resolve()) if args.orig else None,
                    "times": times, "bitrates": {label: bps for (label, _), bps in zip(encoded, bitrates)},
                    "frames": []}
    contact_rows: list[list[dict]] = []
    header = [name for name, _, _ in versions]
    print("time(s)  version       hf         hf_flat    retention  banding")
    for timestamp in times:
        raw = {name: extract_frame(path, timestamp) for name, path, _ in versions}
        target_w, target_h = min(f.shape[1] for f in raw.values()), min(f.shape[0] for f in raw.values())
        frames = {name: resize_rgb(frame, (target_w, target_h)) for name, frame in raw.items()}
        metrics: dict[str, dict] = {}
        extras: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for name in header:
            m, flat, std = metric_image(frames[name])
            metrics[name] = m
            extras[name] = (flat, std)
        base = metrics["graded"]["hf_flat"]
        row_entries = []
        for name in header:
            retention = metrics[name]["hf_flat"] / base if base > 0 else 0.0
            metrics[name]["grain_retention"] = retention if name != "graded" else 1.0
            _, std = extras[name]
            row_entries.append({"frame": frames[name], "crop": flat_crop(frames[name], std),
                                "retention": metrics[name]["grain_retention"]})
            print(f"{timestamp:7.2f}  {name:12} {metrics[name]['hf']:10.4f} {metrics[name]['hf_flat']:10.4f} "
                  f"{metrics[name]['grain_retention']:10.4f} {metrics[name]['banding']:9.6f}")
        contact_rows.append(row_entries)
        report["frames"].append({"time": timestamp, "versions": metrics})
    json_path = out / f"{graded.stem}_sim.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    make_contact_sheet(contact_rows, header, out / f"{graded.stem}_sim.png")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
        print(detail, file=sys.stderr)
        raise SystemExit(exc.returncode or 1)
