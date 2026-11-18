"""Codex 追色 dialog: prompt (typed, preset or AI-written) -> Codex re-grades the current
frame -> paired LUT fit -> new 追色 style selected in the main window."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QVBoxLayout)

from ..color.codex_ref import PRESET_HINTS, codex_path


class _CodexWorker(QThread):
    progress = Signal(str)
    prompt_ready = Signal(str)
    style_ready = Signal(str, str, str, str, float)   # name, title, graded path, prompt, fit dE
    failed = Signal(str)

    def __init__(self, mode, clip, t, prompt):
        super().__init__()
        self.mode, self.clip, self.t, self.prompt = mode, clip, t, prompt
        self.procs = []

    def cancel(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()

    def run(self):
        from ..color import codex_ref
        try:
            if self.mode == 'suggest':
                with tempfile.TemporaryDirectory() as tmp:
                    frame = codex_ref.grab_frame(self.clip, self.t, Path(tmp) / 'frame.png')
                    self.progress.emit('Codex 正在看画面写提示词…')
                    self.prompt_ready.emit(codex_ref.suggest_prompt(
                        frame, self.prompt, on_event=self.progress.emit, proc_holder=self.procs))
            else:
                st, res, fit = codex_ref.codex_reference_style(
                    self.clip, self.t, self.prompt, on_event=self.progress.emit, proc_holder=self.procs)
                self.style_ready.emit(st.name, st.title, str(res.graded), res.prompt, fit)
        except Exception as e:
            self.failed.emit(str(e))


class CodexDialog(QDialog):
    style_ready = Signal(str, str)

    def __init__(self, parent, clip: str, t: float):
        super().__init__(parent)
        self.setWindowTitle('Codex AI 追色')
        self.setMinimumWidth(460)
        self.clip, self.t, self.worker = clip, t, None
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f'截取 <b>{Path(clip).name}</b> 第 <b>{t:.1f}s</b> 的画面，让 Codex 按提示词只改色调，'
                           '再从「原帧 → 调色帧」逐像素拟合出 LUT 风格（约 1–2 分钟）。'))
        f = QFormLayout()
        self.preset = QComboBox()
        for label, hint in PRESET_HINTS:
            self.preset.addItem(label, hint)
        self.preset.currentIndexChanged.connect(lambda _: self.text.setPlainText(self.preset.currentData()))
        f.addRow('预设', self.preset)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText('描述想要的调色，例如：阴影偏青、高光暖金、肤色通透、整体低饱和。'
                                     '\n留空 = 让 AI 根据画面自己决定。')
        self.text.setFixedHeight(90)
        f.addRow('提示词', self.text)
        v.addLayout(f)
        row = QHBoxLayout()
        self.b_suggest = QPushButton('AI 写提示词')
        self.b_suggest.setToolTip('让 Codex 看当前画面，结合上面的想法写一段具体的调色提示词（不生图）')
        self.b_suggest.clicked.connect(lambda: self._start('suggest'))
        self.b_go = QPushButton('生成并追色')
        self.b_go.setDefault(True)
        self.b_go.clicked.connect(lambda: self._start('generate'))
        self.b_cancel = QPushButton('取消')
        self.b_cancel.clicked.connect(self._cancel)
        row.addWidget(self.b_suggest)
        row.addStretch(1)
        row.addWidget(self.b_go)
        row.addWidget(self.b_cancel)
        v.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.preview)
        if not codex_path():
            self.status.setText('没有找到 codex 命令：请先安装 Codex CLI（npm i -g @openai/codex）并登录。')
            self.b_go.setEnabled(False)
            self.b_suggest.setEnabled(False)

    def _busy(self, busy: bool):
        self.b_go.setEnabled(not busy)
        self.b_suggest.setEnabled(not busy)
        self.preset.setEnabled(not busy)
        self.text.setReadOnly(busy)

    def _start(self, mode):
        self._busy(True)
        self.status.setText('正在截取画面…')
        self.worker = _CodexWorker(mode, self.clip, self.t, self.text.toPlainText().strip())
        self.worker.progress.connect(self.status.setText)
        self.worker.prompt_ready.connect(self._prompt_ready)
        self.worker.style_ready.connect(self._style_ready)
        self.worker.failed.connect(lambda e: self.status.setText('失败：' + e))
        self.worker.finished.connect(lambda: self._busy(False))
        self.worker.start()

    def _prompt_ready(self, prompt):
        self.text.setPlainText(prompt)
        self.status.setText('提示词已生成，可以修改后点「生成并追色」。')

    def _style_ready(self, name, title, graded, prompt, fit):
        if prompt:
            self.text.setPlainText(prompt)
        quality = '很接近' if fit < 4 else '基本接近' if fit < 8 else '偏差较大（AI 可能加了局部光效）'
        self.status.setText(f'已生成风格「{title}」，LUT 与 Codex 调色图 {quality}（平均 ΔE {fit:.1f}）。')
        pix = QPixmap(graded)
        if not pix.isNull():
            self.preview.setPixmap(pix.scaled(420, 300, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        self.style_ready.emit(name, title)

    def _cancel(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.status.setText('已取消')
        else:
            self.close()

    def closeEvent(self, e):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(e)
