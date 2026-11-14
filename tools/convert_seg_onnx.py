"""Convert the bundled MediaPipe TFLite segmenter with the supplied conversion venv.

Run from any directory with ``python tools/convert_seg_onnx.py``. No downloads or
package installation are performed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "models" / "selfie_multiclass_256x256.tflite"
DEST = ROOT / "models" / "selfie_multiclass_256x256.onnx"
CONVERTER = ROOT / ".cv" / "Scripts" / "python.exe"


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    if not CONVERTER.is_file():
        raise FileNotFoundError(f"Conversion interpreter not found: {CONVERTER}")
    subprocess.run([
        str(CONVERTER), "-m", "tf2onnx.convert", "--tflite", str(SOURCE),
        "--output", str(DEST), "--opset", "17",
    ], cwd=ROOT, check=True)
    print(f"Wrote {DEST} ({DEST.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
