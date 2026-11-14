"""cake — 短视频风格化调色 + 人像精修.

  python -m cake ui [视频...]                                  # 桌面界面

  python -m cake grade  in.mp4 [-o out.mp4] --style film_warm [--strength 0.8]
  python -m cake still  in.mp4 --t 2.5 [--style ccd ...] [-o sheet.jpg]
  python -m cake styles
  python -m cake probe  in.mp4
  python -m cake build-luts
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .styles import LUT_DIR, list_styles, load_style
from .core.recipe import Recipe, RetouchCfg


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["ui"]:                       # desktop app; its own argument parser
        from .ui.app import main as ui_main
        return ui_main(argv[1:])
    ap = argparse.ArgumentParser(prog="cake", description="短视频风格化调色")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--strength", type=float, default=1.0, help="整体强度 0~1.5 (默认 1)")
        p.add_argument("--max-short", type=int, default=1080,
                       help="短边上限，默认 1080（抖音/视频号播放分辨率）；0 = 保持原分辨率")
        p.add_argument("--tonemap", default="mobius", choices=["hable", "mobius", "reinhard", "clip"],
                       help="HDR→SDR 色调映射算法")
        p.add_argument("--retouch", type=float, default=0.5,
                       help="人像精修强度 0~1（磨皮+肤色提亮+祛痘+黑眼圈），默认 0.5，0 = 关闭")
        retouch_args(p)

    def retouch_args(p):
        p.add_argument("--spots", type=float, help="祛痘/淡斑强度 0~1（默认随 --retouch）")
        p.add_argument("--eyes", type=float, help="黑眼圈淡化强度 0~1（默认随 --retouch）")
        p.add_argument("--remove-moles", action="store_true", help="连痣一起去掉（默认保留痣）")

    g = sub.add_parser("grade", help="给视频调色（可批量：多个文件或文件夹）")
    g.add_argument("input", nargs="+", help="视频文件或文件夹，可多个")
    g.add_argument("-o", "--output", help="单个文件：输出文件路径；批量：输出文件夹")
    g.add_argument("-s", "--style", help="风格名，或 .json / .cube 路径")
    g.add_argument("--ref", help="reference photo")
    g.add_argument("--per-shot", action="store_true")
    g.add_argument("--method", choices=("grade", "mkl"), default="grade")
    g.add_argument("--start", type=float)
    g.add_argument("--duration", type=float)
    g.add_argument("--encoder", default="auto", choices=["auto", "nvenc", "mf", "hevc", "x264"],
                   help="auto = NVENC > Media Foundation 硬件编码 > x264")
    common(g)

    s = sub.add_parser("still", help="截一帧，输出原片和各风格的对比图")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.add_argument("-s", "--style", action="append", help="可多次指定；默认全部风格")
    s.add_argument("--t", type=float, default=1.0, help="截帧时间（秒）")
    common(s)

    fc = sub.add_parser("face", help="精修检查图：不同精修强度的全图 + 脸部放大")
    sub.add_parser("ui", help="桌面界面（python -m cake ui [视频...]）", add_help=False)
    fc.add_argument("input")
    fc.add_argument("-o", "--output")
    fc.add_argument("-s", "--style", help="叠加某个风格（默认不加风格，只看精修）")
    fc.add_argument("--t", type=float, default=1.0)
    fc.add_argument("--levels", default="0,0.5,1", help="精修强度列表，逗号分隔")
    fc.add_argument("--debug", action="store_true", help="标出检测结果：红=痘/斑，蓝=黑眼圈区域")
    retouch_args(fc)

    rs = sub.add_parser("refstyle", help="Build a reference-photo style")
    rs.add_argument("reference")
    rs.add_argument("clips", nargs="+")
    rs.add_argument("--name")
    rs.add_argument("--per-shot", action="store_true")
    rs.add_argument("--skin-follow", type=float, default=.2)
    rs.add_argument("--method", choices=("grade", "mkl"), default="grade")

    sub.add_parser("styles", help="列出风格")
    p = sub.add_parser("probe", help="查看视频参数")
    p.add_argument("input")
    sub.add_parser("build-luts", help="重新生成内置风格的 .cube")

    a = ap.parse_args(argv)

    if a.cmd == "refstyle":
        from .refcolor import build_reference_style
        print(build_reference_style(a.reference, a.clips, a.name, a.skin_follow, method=a.method, per_shot=a.per_shot).name)
        return 0
    if a.cmd == "build-luts":
        from .looks import build_luts
        for path in build_luts(LUT_DIR):
            print("写入", path)
        return 0
    if a.cmd == "styles":
        for st in list_styles():
            print(f"{st.name:14s} {st.title}")
        return 0
    if a.cmd == "probe":
        from .probe import probe
        print(probe(a.input).describe())
        return 0

    max_short = getattr(a, "max_short", 1080) or None
    opts = {"spots": getattr(a, "spots", None), "under": getattr(a, "eyes", None),
            "keep_moles": not getattr(a, "remove_moles", False),
            "debug": getattr(a, "debug", False)}
    recipe = Recipe(style='none', strength=getattr(a, 'strength', 1.0),
                    retouch=RetouchCfg(getattr(a, 'retouch', .5), opts['spots'], opts['under'],
                                       opts['keep_moles'], opts['debug']))
    if a.cmd == "grade":
        return _grade(a, max_short, opts)
    if a.cmd == "face":
        from .pipeline import compare_face
        st = load_style(a.style) if a.style else None
        levels = [float(x) for x in a.levels.split(",")]
        out = a.output or str(Path(a.input).with_name(f"{Path(a.input).stem}_face_{a.t:g}s.jpg"))
        recipe.style = st.name if st else 'none'
        print(compare_face(a.input, out, st, a.t, levels, 1080, opts, recipe=recipe))
        return 0
    if a.cmd == "still":
        from .pipeline import compare_still
        styles = [load_style(x) for x in a.style] if a.style else list_styles()
        out = a.output or str(Path(a.input).with_name(f"{Path(a.input).stem}_compare_{a.t:g}s.jpg"))
        recipe.style = styles[0].name if styles else 'none'
        print(compare_still(a.input, out, styles, a.t, a.strength, max_short, tonemap=a.tonemap,
                            retouch=a.retouch, recipe=recipe))
        return 0
    return 1


VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi"}


def _grade(a, max_short, opts) -> int:
    import time
    from .pipeline import grade_video
    files = []
    for x in a.input:
        p = Path(x)
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXT)
        else:
            files.append(p)
    if not files:
        print("没有找到视频文件")
        return 1
    if a.ref:
        from .refcolor import build_reference_style
        st = build_reference_style(a.ref, [str(f) for f in files], method=a.method, per_shot=a.per_shot)
    elif a.style:
        st = load_style(a.style)
    else:
        raise ValueError("grade requires --style or --ref")
    recipe = Recipe(style=st.name, strength=a.strength,
                    retouch=RetouchCfg(a.retouch, opts['spots'], opts['under'], opts['keep_moles']))
    if len(files) == 1:
        f = files[0]
        out = a.output or str(f.with_name(f"{f.stem}_{st.name}.mp4"))
        grade_video(str(f), out, st, a.strength, max_short, a.start, a.duration, a.encoder,
                    a.tonemap, a.retouch, opts, recipe=recipe)
        return 0

    # batch: one set of warm worker processes for every video (start-up paid once)
    out_dir = Path(a.output) if a.output else files[0].parent / "cake_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    analyzer = None
    if a.retouch > 0 or (st.skin_lut and st.skin_protect > 0):
        from .face import Analyzer
        analyzer = Analyzer()
    failed = []
    t0 = time.perf_counter()
    try:
        for i, f in enumerate(files, 1):
            print(f"\n[{i}/{len(files)}] {f.name}")
            try:
                grade_video(str(f), str(out_dir / f"{f.stem}_{st.name}.mp4"), st, a.strength,
                            max_short, a.start, a.duration, a.encoder, a.tonemap, a.retouch,
                            opts, analyzer=analyzer, recipe=recipe)
            except Exception as e:          # keep going; report at the end
                failed.append((f.name, str(e).splitlines()[0]))
                print(f"  失败: {e}")
    finally:
        if analyzer is not None:
            analyzer.close()
    print(f"\n批量完成: {len(files) - len(failed)}/{len(files)} 成功, "
          f"共 {time.perf_counter() - t0:.1f}s -> {out_dir}")
    for name, err in failed:
        print(f"  失败 {name}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
