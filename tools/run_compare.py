"""Run the 剪映 / Wink head-to-head on samples/对比测试.

Layout (put competitor exports in the matching folder, file name must start
with the original clip's stem, e.g. 剪映/asian_hush_48036.mp4):
    samples/对比测试/ours/<stem>_none.mp4
    samples/对比测试/剪映/<stem>*.mp4
    samples/对比测试/wink/<stem>*.mp4

Outputs to samples/对比测试/结果/:
    frames/        PNG frames at the probe times (all scaled to the original size)
    sheet_*.jpg    compare_reference sheets (ours vs each competitor)
    flicker_*/     tools/flicker.py output per processed clip
    blind_*.mp4    side-by-side A | B with random order, answer in blind_key.json
    summary.txt    all metric tables in one place
"""
import json
import os
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "samples" / "对比测试"
OUT = BASE / "结果"
SAMPLES = ROOT / "samples"
CLIPS = ["asian_closeup_v_101040", "asian_thought_v_101042", "asian_hush_48036", "asian_mother_child_48689"]
COMPETITORS = ["剪映", "wink"]
PY = sys.executable
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def size(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, encoding="utf-8", check=True)
    d = json.loads(r.stdout)
    s = d["streams"][0]
    return int(s["width"]), int(s["height"]), float(d["format"]["duration"])


def grab(video, t, w, h, dest):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                    "-vf", f"scale={w}:{h}:flags=lanczos", str(dest)], check=True)


def run(cmd, log):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV)
    log.write(f"$ {' '.join(map(str, cmd[1:]))}\n{r.stdout}{r.stderr}\n")
    log.flush()
    print(r.stdout, r.stderr, sep="")


def blind(left, right, w, h, dest):
    # Each side scaled to short edge 720, original first in a small strip is not shown: pure A|B.
    vf = (f"[0:v]scale=-2:{min(h, 1280) if h > w else 720},setsar=1[a];"
          f"[1:v]scale=-2:{min(h, 1280) if h > w else 720},setsar=1[b];"
          "[a][b]hstack=shortest=1,drawtext=text='A':x=20:y=20:fontsize=48:fontcolor=white:box=1:boxcolor=black@0.5,"
          "drawtext=text='B':x=w/2+20:y=20:fontsize=48:fontcolor=white:box=1:boxcolor=black@0.5[v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(left), "-i", str(right), "-filter_complex", vf,
                    "-map", "[v]", "-an", "-c:v", "libx264", "-crf", "16", "-preset", "fast", str(dest)], check=True)


def main():
    (OUT / "frames").mkdir(parents=True, exist_ok=True)
    key = {}
    rng = random.Random()
    with open(OUT / "summary.txt", "w", encoding="utf-8") as log:
        for stem in CLIPS:
            orig = SAMPLES / f"{stem}.mp4"
            ours = BASE / "ours" / f"{stem}_none.mp4"
            w, h, dur = size(orig)
            times = [round(dur * f, 2) for f in (0.2, 0.5, 0.8)]
            log.write(f"\n==================== {stem}  {w}x{h}  times={times}\n")
            run([PY, str(ROOT / "tools" / "flicker.py"), str(orig), str(ours), "--out", str(OUT / f"flicker_ours_{stem}")], log)
            for comp in COMPETITORS:
                found = sorted((BASE / comp).glob(f"{stem}*.mp4"))
                if not found:
                    log.write(f"[{comp}] 没有找到 {stem}*.mp4，跳过\n")
                    continue
                theirs = found[0]
                run([PY, str(ROOT / "tools" / "flicker.py"), str(orig), str(theirs), "--out", str(OUT / f"flicker_{comp}_{stem}")], log)
                for t in times:
                    names = {}
                    for tag, v in (("orig", orig), ("ours", ours), (comp, theirs)):
                        p = OUT / "frames" / f"{stem}_{t:g}s_{tag}.png"
                        grab(v, t, w, h, p)
                        names[tag] = p
                    log.write(f"--- {comp} @ {t:g}s (列顺序：原片 / ours / {comp})\n")
                    run([PY, str(ROOT / "tools" / "compare_reference.py"), str(names["orig"]), str(names["ours"]),
                         str(names[comp]), "--out", str(OUT / f"sheet_{comp}_{stem}_{t:g}s.jpg")], log)
                pair = [("ours", ours), (comp, theirs)]
                rng.shuffle(pair)
                dest = OUT / f"blind_{comp}_{stem}.mp4"
                blind(pair[0][1], pair[1][1], w, h, dest)
                key[dest.name] = {"A": pair[0][0], "B": pair[1][0]}
    (OUT / "blind_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"done -> {OUT}  (盲测答案在 blind_key.json，看完再打开)")


if __name__ == "__main__":
    main()
