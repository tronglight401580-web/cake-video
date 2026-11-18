"""Codex 追色: let the local Codex CLI re-grade one frame of the video, then fit a LUT from
the (frame, re-graded frame) pair with `build_paired_style`.

Codex is driven through `codex exec` (non-interactive). The prompt asks it to use its
built-in image generation tool to *edit* the attached frame, changing colour and tone only,
so the result is pixel-aligned with the frame and every pixel becomes a colour sample.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from ..core.config import ROOT

REF_DIR = ROOT / 'refs' / 'codex'

# Ready-made looks for the UI drop-down: (label, hint passed to Codex). '' = let the AI decide.
PRESET_HINTS = [
    ('让 AI 根据画面决定', ''),
    ('电影青橙', '电影感青橙调：阴影偏青、高光和肤色偏暖橙，对比略增'),
    ('日系清新', '日系清新：整体提亮、低对比、低饱和，偏青绿，空气感，白色干净'),
    ('胶片暖调', '胶片暖调：暖黄高光、略褪色的黑位、柔和对比，复古胶片质感'),
    ('港风复古', '港风复古：浓郁红绿、偏洋红阴影、高饱和、浓郁对比'),
    ('奶油肤色', '奶油色调：低饱和暖白、柔和高光、肤色白皙通透'),
    ('黑金夜景', '黑金：除暖黄/橙色以外降低饱和，阴影压暗，高光金色'),
]

_RULES = """Hard rules for the edited image (a 3D LUT will be fitted from it, so anything that is
not a global colour mapping cannot be reproduced):
- Change ONLY colour and tone: white balance, tint, saturation, contrast, curves, split toning.
- Keep composition, framing, aspect ratio, people, faces, objects and textures identical.
  Do not crop, zoom, re-frame, retouch, add or remove anything.
- Do NOT add light sources, sun flares, glows, haze, vignettes, grain, bokeh or text.
- Keep skin natural and believable."""

_SUGGEST = """Look at the attached video frame and write ONE concise colour-grading instruction
(Chinese, at most 80 characters) for an image editor, describing the target look in terms of
white balance, shadow/highlight tint, saturation, contrast and skin tone.
User's wish (may be empty or vague): {hint}
Do not generate any image. Return the instruction only."""

_GENERATE = """Use your image generation tool to EDIT the attached photo (a frame from a video)
with this colour grade:

{prompt}

{rules}

Save the edited image as PNG at exactly this absolute path:
{out}
If the tool saved it elsewhere, copy it there. Do not run any other commands.
Finish with the absolute path of the saved file and the grading instruction you used."""

_SCHEMA_PROMPT = {'type': 'object', 'additionalProperties': False,
                  'properties': {'prompt': {'type': 'string'}}, 'required': ['prompt']}
_SCHEMA_IMAGE = {'type': 'object', 'additionalProperties': False,
                 'properties': {'image': {'type': 'string'}, 'prompt': {'type': 'string'}},
                 'required': ['image', 'prompt']}


class CodexError(RuntimeError):
    pass


@dataclass
class CodexResult:
    frame: Path        # the source frame sent to Codex
    graded: Path       # Codex's re-graded frame
    prompt: str        # grading instruction actually used


def codex_path() -> str | None:
    """Absolute path of the codex CLI (env CAKE_CODEX overrides), or None if not installed."""
    return os.environ.get('CAKE_CODEX') or shutil.which('codex')


def _codex_home() -> Path:
    return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')


def _run(prompt: str, image: Path, workdir: Path, schema: dict, sandbox: str, timeout: float,
         on_event: Callable[[str], None] | None, proc_holder: list | None = None) -> tuple[dict, str]:
    exe = codex_path()
    if not exe:
        raise CodexError('没有找到 codex 命令：请先安装 Codex CLI (npm i -g @openai/codex) 并登录')
    schema_file = workdir / 'schema.json'
    schema_file.write_text(json.dumps(schema), encoding='utf-8')
    last = workdir / 'last.json'
    cmd = [exe, 'exec', '--skip-git-repo-check', '--ephemeral', '--json', '-s', sandbox,
           '-C', str(workdir), '--output-schema', str(schema_file), '-o', str(last),
           '-i', str(image), '-']   # '-' = prompt from stdin; -i takes several values
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=workdir, creationflags=flags)
    if proc_holder is not None:
        proc_holder.append(proc)
    proc.stdin.write(prompt.encode('utf-8'))
    proc.stdin.close()
    thread_id, err_lines = '', []
    t = threading.Thread(target=lambda: err_lines.extend(proc.stderr.read().decode('utf-8', 'replace').splitlines()),
                         daemon=True)
    t.start()
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    try:
        for raw in proc.stdout:
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if ev.get('type') == 'thread.started':
                thread_id = ev.get('thread_id', '')
            item = ev.get('item') or {}
            if on_event and ev.get('type') == 'item.started' and item.get('type') == 'image_generation':
                on_event('Codex 正在生成调色图…')
            elif (on_event and ev.get('type') == 'item.completed' and item.get('type') == 'agent_message'
                  and not item.get('text', '').lstrip().startswith('{')):   # final JSON is returned, not logged
                on_event('Codex: ' + item.get('text', '')[:80])
            elif ev.get('type') in ('turn.failed', 'error'):
                err_lines.append(json.dumps(ev.get('error') or ev, ensure_ascii=False))
        code = proc.wait()
    finally:
        timer.cancel()
        t.join(2)
    if code != 0 or not last.exists():
        tail = '\n'.join(l for l in err_lines if 'failed to load skill' not in l)[-600:]
        raise CodexError(f'codex exec 失败 (exit {code})' + (f': {tail}' if tail else ''))
    text = last.read_text(encoding='utf-8', errors='replace').strip()
    try:
        return json.loads(text), thread_id
    except ValueError:
        return {'prompt': text, 'image': ''}, thread_id


def grab_frame(clip: str, t: float, out: Path, max_short: int = 1080) -> Path:
    """Decode the frame at `t` seconds exactly as the export pipeline sees it (SDR, tonemapped)."""
    from ..io.probe import probe
    from ..io.media import target_size
    from ..pipeline.stills import _grab_frame
    info = probe(str(clip))
    w, h = target_size(info, max_short)
    t = min(max(0.0, t), max(0.0, info.duration - 1 / float(info.fps)))
    raw = _grab_frame(info, t, w, h, False, 'mobius')
    Image.fromarray(np.frombuffer(raw, np.uint8).reshape(h, w, 3)).save(out)
    return out


def suggest_prompt(frame: str | Path, hint: str = '', timeout: float = 240,
                   on_event: Callable[[str], None] | None = None, proc_holder: list | None = None) -> str:
    """Ask Codex to look at the frame and write a grading instruction (no image generated)."""
    with tempfile.TemporaryDirectory(prefix='cake_codex_') as tmp:
        tmp = Path(tmp)
        img = tmp / 'frame.png'
        shutil.copyfile(frame, img)
        data, _ = _run(_SUGGEST.format(hint=hint.strip() or '（无，按画面内容自由发挥）'), img, tmp,
                       _SCHEMA_PROMPT, 'read-only', timeout, on_event, proc_holder)
    prompt = (data.get('prompt') or '').strip()
    if not prompt:
        raise CodexError('Codex 没有返回提示词')
    return prompt


def generate_graded(frame: str | Path, prompt: str, out: str | Path, timeout: float = 600,
                    on_event: Callable[[str], None] | None = None, proc_holder: list | None = None) -> tuple[Path, str]:
    """Have Codex re-grade `frame` per `prompt`; saves PNG to `out`. Returns (path, prompt used)."""
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not prompt.strip():
        prompt = '根据画面内容自行选择一种适合短视频的高级调色风格，并在回复里写明你用的调色指令'
    with tempfile.TemporaryDirectory(prefix='cake_codex_') as tmp:
        tmp = Path(tmp)
        img = tmp / 'frame.png'
        shutil.copyfile(frame, img)
        target = tmp / 'graded.png'
        data, thread = _run(_GENERATE.format(prompt=prompt.strip(), rules=_RULES, out=target), img, tmp,
                            _SCHEMA_IMAGE, 'workspace-write', timeout, on_event, proc_holder)
        # Codex keeps every generated image under $CODEX_HOME/generated_images/<thread>/; prefer
        # that original: the copy in the sandboxed workdir can be unreadable for a moment
        # (Windows sandbox ACLs / file locks).
        candidates = []
        gen = _codex_home() / 'generated_images' / thread if thread else None
        if gen is not None and gen.is_dir():
            candidates += sorted(gen.glob('*.png'), key=lambda p: p.stat().st_mtime, reverse=True)
        candidates += [target, Path(data.get('image') or target)]
        last_err = None
        for p in candidates:
            if not p.is_file() or p.resolve() == img.resolve():
                continue
            for _ in range(5):
                try:
                    with Image.open(p) as im:
                        im.convert('RGB').save(out)
                    return out, (data.get('prompt') or prompt).strip()
                except PermissionError as e:
                    last_err = e
                    time.sleep(.5)
        detail = f'：{last_err}' if last_err else '（检查 codex 的 image_generation 功能是否开启、账号是否支持生图）'
        raise CodexError('Codex 没有生成可读取的图片' + detail)


def codex_reference_style(clip: str, t: float, prompt: str = '', name: str | None = None,
                          skin_follow: float = .2, graded: str | None = None, timeout: float = 600,
                          on_event: Callable[[str], None] | None = None, proc_holder: list | None = None):
    """Full flow: grab frame -> Codex re-grade (skipped when `graded` is given) -> paired LUT fit.
    Returns (Style, CodexResult, fit_de76)."""
    from .refcolor import build_paired_style
    REF_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    slug = name or f'codex_{stamp}'
    frame = grab_frame(clip, t, REF_DIR / f'{slug}_src.png')
    if graded:   # keep a copy next to the frame so the style's reference thumbnail survives
        out, used = REF_DIR / f'{slug}.png', prompt
        with Image.open(graded) as im:
            im.convert('RGB').save(out)
    else:
        if on_event:
            on_event('已截取 %.1fs 画面，正在调用 Codex…' % t)
        out, used = generate_graded(frame, prompt, REF_DIR / f'{slug}.png', timeout, on_event, proc_holder)
    if on_event:
        on_event('正在根据调色图拟合 LUT…')
    style, fit = build_paired_style(frame, out, name=slug, skin_follow=skin_follow, reference=str(out))
    if used:
        (REF_DIR / f'{slug}.txt').write_text(used, encoding='utf-8')
    return style, CodexResult(frame, out, used), fit
