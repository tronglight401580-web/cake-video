"""Smoke test for platform_sim.py; run with python tools/test_platform_sim.py."""

import json
import subprocess
import tempfile
from pathlib import Path

from platform_sim import main


def test_platform_sim() -> None:
    with tempfile.TemporaryDirectory(prefix="platform_sim_") as temp:
        root = Path(temp)
        clip = root / "graded.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=1080x1920:rate=24:duration=4",
            "-vf", "noise=alls=20:allf=t", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", str(clip),
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        out = root / "out"
        assert main([str(clip), "--out", str(out)]) == 0
        assert (out / "graded_3M.mp4").is_file()
        assert (out / "graded_1.5M.mp4").is_file()
        report_path = out / "graded_sim.json"
        sheet_path = out / "graded_sim.png"
        assert report_path.is_file()
        assert sheet_path.is_file()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert len(report["frames"]) == 3
        for frame in report["frames"]:
            for label in ("3M", "1.5M"):
                retention = frame["versions"][label]["grain_retention"]
                assert 0 < retention <= 1.5, (label, retention)


if __name__ == "__main__":
    test_platform_sim()
    print("platform_sim test passed")
