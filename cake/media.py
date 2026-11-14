"""ffmpeg decode -> raw RGB frames, and raw RGB frames -> ffmpeg encode (NVENC)."""
from __future__ import annotations

import subprocess
from fractions import Fraction

from .probe import ClipInfo

# Encoders. NVENC on GTX 10xx: h264/hevc yes, AV1 no.
ENCODERS = {
    "nvenc": ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr",
              "-cq", "19", "-b:v", "16M", "-maxrate", "24M", "-bufsize", "32M",
              "-spatial-aq", "1", "-bf", "3", "-profile:v", "high"],
    "hevc": ["-c:v", "hevc_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr",
             "-cq", "21", "-b:v", "12M", "-maxrate", "18M", "-bufsize", "24M",
             "-spatial-aq", "1", "-tag:v", "hvc1"],
    # 'faster': ~2x the speed of 'fast' at CRF 17 with near-identical size; CPU is shared with
    # the face analysis when retouching, and the platform re-encodes anyway.
    # Windows Media Foundation hardware H.264 (on NVIDIA this is NVENC via the driver's MFT -
    # works with drivers too old for this ffmpeg's NVENC API). Wants NV12. Profile 100 = High.
    "mf": ["-c:v", "h264_mf", "-hw_encoding", "1", "-profile:v", "100",
           "-rate_control", "u_vbr", "-b:v", "16M", "-maxrate", "24M"],
    "x264": ["-c:v", "libx264", "-preset", "faster", "-crf", "17", "-profile:v", "high",
             "-x264-params", "aq-mode=3"],
}
MP4_AUDIO_COPY_OK = {"aac", "mp3", "alac", "ac3", "eac3"}

_encoder_ok: dict[str, bool] = {}


def encoder_available(name: str) -> bool:
    """NVENC needs a driver new enough for this ffmpeg build's NVENC API (ffmpeg 8.1 -> 610+),
    so actually try a tiny encode instead of trusting the encoder list."""
    if name not in _encoder_ok:
        cmd = ["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=s=256x256:d=0.2",
               "-pix_fmt", "nv12", *ENCODERS[name], "-f", "null", "-"]
        r = subprocess.run(cmd, capture_output=True)
        _encoder_ok[name] = r.returncode == 0
    return _encoder_ok[name]


def pick_encoder(requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    for name in ("nvenc", "mf", "x264"):
        if encoder_available(name):
            return name
    return "x264"


def target_size(info: ClipInfo, max_short: int | None) -> tuple[int, int]:
    """Output size: downscale so the short side <= max_short (platforms play 1080p), keep even."""
    w, h = info.width, info.height
    if max_short and min(w, h) > max_short:
        k = max_short / min(w, h)
        w, h = round(w * k), round(h * k)
    return w - w % 2, h - h % 2


def source_matrix(info: ClipInfo) -> tuple[str, str]:
    """(matrix, range) of an SDR source: 'bt709'/'bt601', 'tv'/'pc'.
    Untagged HD video is almost always BT.709 (swscale would wrongly assume 601)."""
    matrix = info.matrix if info.matrix not in ("unknown", "", None) else (
        "bt709" if max(info.width, info.height) >= 1000 else "bt601")
    matrix = {"bt470bg": "bt601", "smpte170m": "bt601"}.get(matrix, matrix)
    if matrix not in ("bt709", "bt601"):
        matrix = "bt709"
    return matrix, ("pc" if info.color_range == "pc" else "tv")


def yuv_capable(info: ClipInfo, high_bit: bool) -> bool:
    """8-bit SDR BT.709/601 sources can be piped as YUV and converted to RGB on the GPU."""
    return not high_bit and not info.hdr and info.primaries != "bt2020"


def _to_yuv_filters(info: ClipInfo, w: int, h: int) -> str:
    return (f"fps={info.fps.numerator}/{info.fps.denominator},"
            f"scale={w}:{h}:flags=lanczos,format=yuv420p")


def _to_rgb_filters(info: ClipInfo, w: int, h: int, pix_fmt: str, tonemap: str) -> str:
    """Filter chain that turns any phone/camera clip into display-referred Rec.709 RGB."""
    f = [f"fps={info.fps.numerator}/{info.fps.denominator}"]   # force CFR: VFR phone clips
    if info.hdr:
        # HDR (HLG / PQ) -> linear -> BT.709 primaries -> tone map -> BT.709 gamma.
        npl = 203 if info.hdr == "hlg" else 100
        f += [f"zscale=w={w}:h={h}:filter=lanczos:t=linear:npl={npl}",
              "format=gbrpf32le",
              "zscale=p=bt709",
              f"tonemap=tonemap={tonemap}:desat=0",
              "zscale=t=bt709:r=full"]
    elif info.primaries == "bt2020":
        f += [f"zscale=w={w}:h={h}:filter=lanczos:p=bt709:r=full"]
    else:
        matrix, rng = source_matrix(info)
        f += [f"scale={w}:{h}:flags=lanczos+accurate_rnd+full_chroma_int"
              f":in_color_matrix={matrix}:in_range={rng}"]
    f.append(f"format={pix_fmt}")
    return ",".join(f)


class Decoder:
    def __init__(self, info: ClipInfo, w: int, h: int, high_bit: bool,
                 start: float | None = None, duration: float | None = None,
                 frames: int | None = None, tonemap: str = "mobius", yuv: bool = False):
        """yuv=True (only if yuv_capable): frames are I420 (yuv420p) as decoded - no RGB
        conversion in ffmpeg and half the pipe traffic; the renderer converts on the GPU."""
        self.w, self.h = w, h
        self.yuv = yuv
        self.pix_fmt = "yuv420p" if yuv else ("rgb48le" if high_bit else "rgb24")
        self.frame_bytes = w * h * 3 // 2 if yuv else w * h * 3 * (2 if high_bit else 1)
        cmd = ["ffmpeg", "-v", "error", "-nostdin"]
        if start:
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-i", info.path]
        if duration:
            cmd += ["-t", f"{duration:.3f}"]
        if frames:
            cmd += ["-frames:v", str(frames)]
        vf = _to_yuv_filters(info, w, h) if yuv else _to_rgb_filters(info, w, h, self.pix_fmt, tonemap)
        cmd += ["-an", "-sn", "-vf", vf, "-f", "rawvideo", "-pix_fmt", self.pix_fmt, "-"]
        self.cmd = cmd
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     bufsize=self.frame_bytes * 2)

    def __iter__(self):
        read = self.proc.stdout.read
        n = self.frame_bytes
        while True:
            buf = read(n)
            if len(buf) < n:
                break
            yield buf

    def close(self) -> str:
        self.proc.stdout.close()
        err = self.proc.stderr.read().decode("utf-8", "replace")
        self.proc.wait()
        return err

    def kill(self) -> None:
        """Abort mid-stream (seek / load another clip in the preview)."""
        try:
            self.proc.kill()
        except OSError:
            pass
        for s in (self.proc.stdout, self.proc.stderr):
            try:
                s.close()
            except OSError:
                pass
        self.proc.wait()


class Encoder:
    def __init__(self, info: ClipInfo, out: str, w: int, h: int, fps: Fraction,
                 encoder: str = "nvenc", start: float | None = None,
                 duration: float | None = None, yuv: bool = True):
        """yuv=True: frames arrive as NV12 BT.709 limited range (converted on the GPU) -
        no swscale in ffmpeg and half the pipe traffic of rgb24."""
        self.frame_bytes = w * h * 3 // 2 if yuv else w * h * 3
        cmd = ["ffmpeg", "-v", "error", "-y", "-nostdin",
               "-f", "rawvideo", "-pix_fmt", "nv12" if yuv else "rgb24", "-s", f"{w}x{h}",
               "-r", f"{fps.numerator}/{fps.denominator}", "-i", "-"]
        if info.audio_codec:
            if start:
                cmd += ["-ss", f"{start:.3f}"]
            if duration:
                cmd += ["-t", f"{duration:.3f}"]
            cmd += ["-i", info.path, "-map", "0:v", "-map", "1:a:0"]
            if info.audio_codec in MP4_AUDIO_COPY_OK:
                cmd += ["-c:a", "copy"]
            else:
                cmd += ["-c:a", "aac", "-b:a", "256k"]
        tags = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"
        if not yuv:
            cmd += ["-vf", "scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd,"
                           "format=nv12," + tags]
        elif encoder == "x264":
            cmd += ["-vf", tags + ",format=yuv420p"]   # x264 High profile wants planar 4:2:0
        else:
            cmd += ["-vf", tags]
        cmd += ENCODERS[encoder]
        cmd += ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                "-color_range", "tv", "-movflags", "+faststart", out]
        self.cmd = cmd
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                     bufsize=self.frame_bytes * 2)

    def write(self, buf: bytes) -> None:
        self.proc.stdin.write(buf)

    def close(self) -> tuple[int, str]:
        try:
            self.proc.stdin.close()
        except OSError:
            pass   # encoder already died; its stderr says why
        err = self.proc.stderr.read().decode("utf-8", "replace")
        return self.proc.wait(), err
