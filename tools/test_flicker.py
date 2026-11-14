"""Integration test for flicker.py using tiny synthetic ffmpeg clips."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(__file__).with_name("flicker.py")


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Command failed: {cmd}\n{result.stderr}")
    return result


def main():
    with tempfile.TemporaryDirectory(prefix="flicker-test-") as td:
        folder = Path(td)
        original = folder / "original.mp4"
        same = folder / "same.mp4"
        jitter = folder / "jitter.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=540x960:rate=24:duration=2",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0", "-pix_fmt", "yuv420p", str(original)])
        run(["ffmpeg", "-v", "error", "-y", "-i", str(original), "-c", "copy", str(same)])
        # A smooth, frame-varying global exposure change exercises low spatial frequencies.
        run(["ffmpeg", "-v", "error", "-y", "-i", str(original), "-vf",
             "eq=brightness='0.25*sin(2*PI*t*2)':eval=frame", "-c:v", "libx264", "-preset", "ultrafast",
             "-crf", "0", "-pix_fmt", "yuv420p", str(jitter)])
        same_out, jitter_out = folder / "same-out", folder / "jitter-out"
        for source, target in ((same, same_out), (jitter, jitter_out)):
            run([sys.executable, str(SCRIPT), str(original), str(source), "--max-frames", "6",
                 "--out", str(target)])
        identical = json.loads((same_out / "same_flicker.json").read_text(encoding="utf-8"))
        changed = json.loads((jitter_out / "jitter_flicker.json").read_text(encoding="utf-8"))
        same_breath = identical["summary"]["frame_breathing"]["mean"]
        jitter_breath = changed["summary"]["frame_breathing"]["mean"]
        same_shimmer = identical["summary"]["frame_shimmer"]["mean"]
        assert identical["frames_with_face"] == 0 and changed["frames_with_face"] == 0
        assert same_breath < 0.01, f"identical clip should be near zero, got {same_breath}"
        assert jitter_breath > max(1.0, same_breath * 10), (f"jittered breathing should be much higher: "
                                                              f"{jitter_breath} vs {same_breath}")
        print(f"PASS: identical breathing={same_breath:.4f}, identical shimmer={same_shimmer:.4f}, "
              f"jittered breathing={jitter_breath:.4f}; no-face clips handled")


if __name__ == "__main__":
    main()
