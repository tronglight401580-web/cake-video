"""Shared configuration for paths, environment options and processing defaults."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / 'models'
LUT_DIR = ROOT / 'luts'
STYLE_DIR = ROOT / 'styles'
PRESETS_FILE = Path(os.environ.get('APPDATA', Path.home())) / 'cake' / 'presets.json'
CAKE_SEG = os.environ.get('CAKE_SEG', 'auto')
CAKE_ANALYZER = os.environ.get('CAKE_ANALYZER', 'process')
CAKE_YUV = os.environ.get('CAKE_YUV') == '1'
ANALYSIS_SHORT = 360
SEG_EVERY = 2
PROCESS_WORKERS = 3
THREAD_WORKERS = 4
PREVIEW_SHORT = 720
LOOKAHEAD = 6

SEGMENTATION_MODEL = MODEL_DIR / "selfie_multiclass_256x256.onnx"

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
