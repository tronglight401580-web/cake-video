"""ffprobe wrapper: everything the pipeline needs to know about an input clip."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction

HDR_TRANSFERS = {"smpte2084": "pq", "arib-std-b67": "hlg"}
HIGH_BIT_FMTS = ("10", "12", "16", "p010", "p016")
STANDARD_FPS = (23.976, 24, 25, 29.97, 30, 48, 50, 59.94, 60, 120)


@dataclass
class ClipInfo:
    path: str
    width: int           # display width (after rotation)
    height: int          # display height (after rotation)
    fps: Fraction        # constant output rate we will render at
    duration: float
    pix_fmt: str
    transfer: str        # raw color_transfer tag
    primaries: str
    matrix: str
    color_range: str
    rotation: int
    audio_codec: str | None

    @property
    def hdr(self) -> str | None:
        """'pq', 'hlg' or None."""
        return HDR_TRANSFERS.get(self.transfer)

    @property
    def high_bit(self) -> bool:
        return any(tag in self.pix_fmt for tag in HIGH_BIT_FMTS)

    def describe(self) -> str:
        hdr = self.hdr.upper() if self.hdr else "SDR"
        bit = "10bit+" if self.high_bit else "8bit"
        return (f"{self.width}x{self.height} @ {float(self.fps):.3f}fps, {self.duration:.2f}s, "
                f"{hdr} {bit} ({self.pix_fmt}, trc={self.transfer}, prim={self.primaries}), "
                f"rot={self.rotation}, audio={self.audio_codec or 'none'}")


def _ffprobe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True, check=True,
    ).stdout
    return json.loads(out.decode("utf-8", "replace"))


def _snap_fps(rate: Fraction) -> Fraction:
    """Phone footage is often VFR (avg 29.87 etc). Snap to the nearest standard rate."""
    best = min(STANDARD_FPS, key=lambda s: abs(s - float(rate)))
    if abs(best - float(rate)) / best < 0.03:
        if best in (23.976, 29.97, 59.94):
            return Fraction(round(best * 1001 / 1000) * 1000, 1001)
        return Fraction(int(best))
    return rate.limit_denominator(1001)


def probe(path: str) -> ClipInfo:
    data = _ffprobe(path)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), None)
    if v is None:
        raise ValueError(f"no video stream in {path}")
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)

    rotation = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(round(float(sd["rotation"])))
    if not rotation and "rotate" in v.get("tags", {}):
        rotation = -int(v["tags"]["rotate"])
    w, h = int(v["width"]), int(v["height"])
    if rotation % 180 != 0:
        w, h = h, w

    rate = Fraction(v.get("avg_frame_rate") or "0/1")
    if rate == 0:
        rate = Fraction(v.get("r_frame_rate") or "30/1")
    duration = float(v.get("duration") or data.get("format", {}).get("duration") or 0)

    return ClipInfo(
        path=path, width=w, height=h, fps=_snap_fps(rate), duration=duration,
        pix_fmt=v.get("pix_fmt", "yuv420p"),
        transfer=v.get("color_transfer", "unknown"),
        primaries=v.get("color_primaries", "unknown"),
        matrix=v.get("color_space", "unknown"),
        color_range=v.get("color_range", "tv"),
        rotation=rotation,
        audio_codec=a.get("codec_name") if a else None,
    )
