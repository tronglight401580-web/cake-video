"""Main window: queue (left) | preview with before/after split (centre) | parameters (right).

    python -m cake ui [videos...]
    python -m cake ui clip.mp4 --t 3 --screenshot shot.png      # automated check: grab + quit
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QSlider, QSplitter, QVBoxLayout, QWidget)

import json
import os
import subprocess
import threading

from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut

from ..styles import list_styles, load_style
from .engine import PreviewEngine
from .preview_view import PreviewView
from .export_worker import ExportWorker
from .param_panel import ParamPanel, _slider
from .queue_panel import QueuePanel, ROLE_PATH, ROLE_SETTINGS, VIDEO_EXT
from .bus_qt import QtBusBridge

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi"}
ROLE_PATH = Qt.ItemDataRole.UserRole
ROLE_SETTINGS = Qt.ItemDataRole.UserRole + 1








QSS = """
QWidget { background: #1e1f22; color: #e6e6e6; font-family: "Microsoft YaHei UI"; font-size: 13px; }
QGroupBox { border: 1px solid #34363b; border-radius: 6px; margin-top: 14px; padding: 8px 6px 6px 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #9aa0a6; }
QPushButton { background: #2d2f34; border: 1px solid #3a3d43; border-radius: 5px; padding: 5px 10px; }
QPushButton:hover { background: #363940; }
QPushButton:disabled { color: #6b6f76; }
QPushButton#primary { background: #2f6fde; border-color: #2f6fde; color: white; }
QPushButton#primary:hover { background: #3b7cf0; }
QListWidget { background: #17181b; border: 1px solid #2c2e33; border-radius: 6px; }
QListWidget::item { padding: 6px 4px; }
QListWidget::item:selected { background: #2b4a7e; }
QComboBox, QLineEdit { background: #26282c; border: 1px solid #3a3d43; border-radius: 5px; padding: 4px 6px; }
QSlider::groove:horizontal { height: 4px; background: #3a3d43; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #2f6fde; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -6px 0; border-radius: 7px; background: #e6e6e6; }
QProgressBar { border: 1px solid #3a3d43; border-radius: 4px; text-align: center; height: 16px; }
QProgressBar::chunk { background: #2f6fde; border-radius: 3px; }
QStatusBar { color: #9aa0a6; }
"""


# --------------------------------------------------------------------------- preview widget




# --------------------------------------------------------------------------- export worker


# --------------------------------------------------------------------------- main window


class MainWindow(ParamPanel, QueuePanel, QMainWindow):
    thumb_ready = Signal(str, bytes)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("视频调色 · 精修")
        self.resize(1440, 900)
        self.setAcceptDrops(True)
        self.bus_bridge = QtBusBridge(self)
        self.bus_bridge.status.connect(self._on_bus_status)
        self.bus_bridge.progress.connect(self._on_bus_progress)
        self.bus_bridge.error.connect(self._on_bus_error)
        self.engine = PreviewEngine()
        self.duration = 0.0
        self.fps = 30.0
        self.playing = False
        self.export_worker: ExportWorker | None = None
        self.spots_touched = self.eyes_touched = False
        self.frames_seen = 0

        self.param_timer = QTimer(self, singleShot=True, interval=40)
        self.seek_timer = QTimer(self, singleShot=True, interval=120)
        self.view = PreviewView()
        splitter = QSplitter()
        splitter.addWidget(self._build_queue())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_params())
        splitter.setSizes([260, 880, 300])
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("就绪")

        self.param_timer.timeout.connect(self._send_params)
        self.seek_timer.timeout.connect(self._do_seek)

        e = self.engine
        e.frame_ready.connect(self._on_frame)
        e.clip_loaded.connect(self._on_loaded)
        e.playing_changed.connect(self._on_playing)
        e.status.connect(self.statusBar().showMessage)
        e.error.connect(lambda m: QMessageBox.critical(self, "预览出错", m[:2000]))
        e.start()
        self._send_params()
        # parse every style's LUT in the background so switching styles is instant
        threading.Thread(target=lambda: [s.load_lut() for s in list_styles()], daemon=True).start()
        self.thumb_ready.connect(self._set_thumb)
        self._applying = False         # True while settings are pushed into the widgets
        self._install_shortcuts()

    # ---------------------------------------------------------------- layout

    def _build_center(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 8, 4, 8)
        v.addWidget(self.view, 1)
        bar = QHBoxLayout()
        self.play_btn = QPushButton("▶ 播放")
        self.play_btn.setFixedWidth(90)
        self.play_btn.clicked.connect(self._toggle_play)
        self.timeline = _slider(0, 1000, 0)
        self.timeline.sliderMoved.connect(lambda _: self.seek_timer.start())
        self.timeline.sliderReleased.connect(self._do_seek)
        self.time_label = QLabel("00:00 / 00:00")
        self.mode_box = QComboBox()
        for text, m in (("左右对比", "split"), ("只看效果", "effect"), ("只看原片", "original")):
            self.mode_box.addItem(text, m)
        self.mode_box.currentIndexChanged.connect(self._on_mode)
        bar.addWidget(self.play_btn)
        bar.addWidget(self.timeline, 1)
        bar.addWidget(self.time_label)
        bar.addWidget(self.mode_box)
        v.addLayout(bar)
        return w


    # ---------------------------------------------------------------- params








    # ---------------------------------------------------------------- presets





    # ---------------------------------------------------------------- shortcuts
    def _install_shortcuts(self):
        def sc(key, fn):
            s = QShortcut(QKeySequence(key), self)
            s.setContext(Qt.ShortcutContext.ApplicationShortcut)
            s.activated.connect(fn)
        sc(Qt.Key.Key_Space, self._toggle_play)
        sc(Qt.Key.Key_Right, lambda: self.engine.step(+1))
        sc(Qt.Key.Key_Left, lambda: self.engine.step(-1))
        sc(Qt.Key.Key_Up, lambda: self.queue.setCurrentRow(max(0, self.queue.currentRow() - 1)))
        sc(Qt.Key.Key_Down, lambda: self.queue.setCurrentRow(
            min(self.queue.count() - 1, self.queue.currentRow() + 1)))
        sc("Ctrl+O", self._add_files)
        sc("Ctrl+E", lambda: self._export(all_items=False))
        sc("Ctrl+Shift+E", lambda: self._export(all_items=True))

    def keyPressEvent(self, e):
        # hold "\" to see the original (like a before/after toggle in photo editors)
        if e.key() == Qt.Key.Key_Backslash and not e.isAutoRepeat():
            self._mode_before_hold = self.view.mode
            self.view.mode = "original"
            self.view.update()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key.Key_Backslash and not e.isAutoRepeat():
            self.view.mode = getattr(self, "_mode_before_hold", self.mode_box.currentData())
            self.view.update()
        else:
            super().keyReleaseEvent(e)

    # ---------------------------------------------------------------- queue







    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths([u.toLocalFile() for u in e.mimeData().urls()])

    # ---------------------------------------------------------------- playback
    def _on_loaded(self, info: dict):
        self.duration, self.fps = info["duration"], info["fps"]
        self.info_lbl.setText(info["desc"])

    def _on_frame(self, graded: QImage, original: QImage, t: float, ms: float):
        self.view.set_images(graded, original)
        self.frames_seen += 1
        if not self.timeline.isSliderDown() and self.duration > 0:
            self.timeline.blockSignals(True)
            self.timeline.setValue(int(1000 * t / self.duration))
            self.timeline.blockSignals(False)
        self.time_label.setText(f"{_mmss(t)} / {_mmss(self.duration)}")
        self.statusBar().showMessage(f"预览 {graded.width()}x{graded.height()} · 渲染 {ms:.0f} ms")

    def _on_playing(self, playing: bool):
        self.playing = playing
        self.play_btn.setText("⏸ 暂停" if playing else "▶ 播放")

    def _toggle_play(self):
        (self.engine.pause if self.playing else self.engine.play)()

    def _do_seek(self):
        if self.duration > 0:
            self.engine.seek(self.timeline.value() / 1000 * self.duration)

    def _on_mode(self):
        self.view.mode = self.mode_box.currentData()
        self.view.update()

    # ---------------------------------------------------------------- export
    def _choose_out(self):
        d = QFileDialog.getExistingDirectory(self, "输出文件夹")
        if d:
            self.out_dir.setText(d)

    def _export(self, all_items: bool):
        if self.export_worker is not None:
            return
        rows = range(self.queue.count()) if all_items else [self.queue.currentRow()]
        jobs = [(r, self.queue.item(r).data(ROLE_PATH),
                 self.queue.item(r).data(ROLE_SETTINGS) or self.settings()) for r in rows if r >= 0]
        if not jobs:
            return
        out_dir = self.out_dir.text().strip() or str(Path(jobs[0][1]).parent / "cake_out")
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        self.last_out_dir = out_dir
        self.open_out.setEnabled(False)
        self.engine.pause()                       # don't fight the export for the CPU
        self.export_worker = w = ExportWorker(jobs, out_dir)
        w.item_started.connect(lambda r, name: self.export_status.setText(f"正在导出 {name} …"))
        w.item_progress.connect(self._on_export_progress)
        w.item_done.connect(self._on_item_done)
        w.all_done.connect(self._on_export_done)
        for b in (self.export_one, self.export_all):
            b.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setValue(0)
        self.export_jobs = len(jobs)
        self.export_index = 0
        w.start()

    def _on_export_progress(self, row: int, n: int, total: int):
        if total:
            part = n / total
            self.progress.setValue(int(100 * (self.export_index + part) / self.export_jobs))

    def _on_bus_status(self, event: dict):
        if event.get('status') == 'started':
            self.statusBar().showMessage(f"正在导出 {Path(event['input']).name}")
        elif event.get('status') == 'completed':
            self.statusBar().showMessage(f"已导出 {Path(event['out']).name}")

    def _on_bus_progress(self, event: dict):
        if self.export_worker is not None and event.get('total'):
            self.export_status.setText(f"已处理 {event['done']}/{event['total']} 帧")

    def _on_bus_error(self, event: dict):
        self.statusBar().showMessage(str(event.get('message', event)))

    def _on_item_done(self, row: int, ok: bool, msg: str):
        self.export_index += 1
        it = self.queue.item(row)
        if it is not None:
            name = Path(it.data(Qt.ItemDataRole.UserRole)).name
            it.setText(("✓ " if ok else "✗ ") + name)
            it.setToolTip(msg)
        self.progress.setValue(int(100 * self.export_index / self.export_jobs))

    def _on_export_done(self, ok: int, total: int, secs: float):
        self.export_status.setText(f"完成 {ok}/{total}，用时 {secs:.1f}s")
        self.open_out.setEnabled(ok > 0)
        for b in (self.export_one, self.export_all):
            b.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.export_worker = None

    def _cancel_export(self):
        if self.export_worker is not None:
            self.export_worker.cancel()
            self.export_status.setText("正在取消…")

    def closeEvent(self, e):
        if self.export_worker is not None:
            self.export_worker.cancel()
            self.export_worker.wait(15000)
        self.engine.stop()
        self.bus_bridge.close()
        super().closeEvent(e)


def _mmss(t: float) -> str:
    t = max(0, int(t))
    return f"{t // 60:02d}:{t % 60:02d}"


# --------------------------------------------------------------------------- entry





