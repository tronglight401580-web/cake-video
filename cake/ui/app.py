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

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi"}
ROLE_PATH = Qt.ItemDataRole.UserRole
ROLE_SETTINGS = Qt.ItemDataRole.UserRole + 1
PRESETS_FILE = Path(os.environ.get("APPDATA", Path.home())) / "cake" / "presets.json"


def load_presets() -> dict:
    try:
        return json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_presets(p: dict) -> None:
    PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PRESETS_FILE.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")


def _thumbnail(path: str, height: int = 56) -> bytes | None:
    """One small JPEG frame for the queue icon (ffmpeg, ~50 ms)."""
    try:
        return subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", path, "-frames:v", "1",
                               "-vf", f"scale=-2:{height}", "-f", "image2pipe", "-c:v", "mjpeg", "-"],
                              capture_output=True, timeout=20).stdout or None
    except (OSError, subprocess.TimeoutExpired):
        return None

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
class PreviewView(QWidget):
    """Shows graded vs original with a draggable split line (or either one alone)."""

    def __init__(self):
        super().__init__()
        self.graded: QImage | None = None
        self.original: QImage | None = None
        self.split = 0.5
        self.mode = "split"            # split | effect | original
        self.setMinimumSize(360, 360)
        self.setMouseTracking(True)

    def set_images(self, graded: QImage, original: QImage):
        self.graded, self.original = graded, original
        self.update()

    def _target(self) -> QRectF:
        img = self.graded or self.original
        if img is None:
            return QRectF(self.rect())
        k = min(self.width() / img.width(), self.height() / img.height())
        w, h = img.width() * k, img.height() * k
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101113"))
        if self.graded is None:
            p.setPen(QColor("#6b6f76"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "把视频拖进来，或点左侧「添加视频」")
            return
        r = self._target()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.mode == "original":
            p.drawImage(r, self.original)
        elif self.mode == "effect":
            p.drawImage(r, self.graded)
        else:
            sx = r.left() + r.width() * self.split
            iw = self.graded.width()
            src_split = iw * self.split
            p.drawImage(QRectF(r.left(), r.top(), sx - r.left(), r.height()), self.original,
                        QRectF(0, 0, src_split, self.original.height()))
            p.drawImage(QRectF(sx, r.top(), r.right() - sx, r.height()), self.graded,
                        QRectF(src_split, 0, iw - src_split, self.graded.height()))
            p.setPen(QPen(QColor(255, 255, 255, 220), 2))
            p.drawLine(QPointF(sx, r.top()), QPointF(sx, r.bottom()))
            p.setBrush(QColor(255, 255, 255, 230))
            p.drawEllipse(QPointF(sx, r.center().y()), 9, 9)
            f = QFont(self.font())
            f.setPointSize(10)
            p.setFont(f)
            for text, x, align in (("原片", r.left() + 10, Qt.AlignmentFlag.AlignLeft),
                                   ("效果", r.right() - 70, Qt.AlignmentFlag.AlignRight)):
                box = QRectF(x, r.top() + 10, 60, 22)
                p.fillRect(box, QColor(0, 0, 0, 140))
                p.setPen(QColor("white"))
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _drag(self, x: float):
        r = self._target()
        if r.width() > 0:
            self.split = min(1.0, max(0.0, (x - r.left()) / r.width()))
            self.update()

    def mousePressEvent(self, e):
        if self.mode == "split" and self.graded is not None:
            self._drag(e.position().x())

    def mouseMoveEvent(self, e):
        if self.mode == "split" and e.buttons() & Qt.MouseButton.LeftButton:
            self._drag(e.position().x())


class ReferenceWorker(QThread):
    ready = Signal(str, str)
    failed = Signal(str)

    def __init__(self, ref, clip):
        super().__init__()
        self.ref, self.clip = ref, clip

    def run(self):
        try:
            from ..refcolor import build_reference_style
            st = build_reference_style(self.ref, [self.clip])
            self.ready.emit(st.name, st.title)
        except Exception as e:
            self.failed.emit(str(e))


# --------------------------------------------------------------------------- export worker
class ExportWorker(QThread):
    item_started = Signal(int, str)
    item_progress = Signal(int, int, int)      # row, done, total
    item_done = Signal(int, bool, str)
    all_done = Signal(int, int, float)         # ok, total, seconds

    def __init__(self, jobs: list[tuple[int, str, dict]], out_dir: str):
        """jobs: (queue row, path, that clip's own settings)."""
        super().__init__()
        self.jobs, self.out_dir = jobs, out_dir
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        from ..pipeline import CancelledError, grade_video
        from ..styles import load_style
        analyzer = None
        ok = 0
        t0 = time.perf_counter()
        try:
            if any(s["retouch"] > 0 or (load_style(s["style"]).skin_lut and load_style(s["style"]).skin_protect > 0) for _, _, s in self.jobs):
                from ..face import Analyzer
                analyzer = Analyzer()             # one warm pool for the whole batch
            for row, path, s in self.jobs:
                if self._cancel:
                    break
                st = load_style(s["style"])
                self.item_started.emit(row, Path(path).name)
                out = str(Path(self.out_dir) / f"{Path(path).stem}_{st.name}.mp4")
                try:
                    grade_video(path, out, st, s["strength"], retouch=s["retouch"],
                                retouch_opts={**s["opts"], "debug": False}, log=lambda *a: None,
                                analyzer=analyzer, skin_protect_scale=s.get("skin_protect", .8) / .8,
                                progress=lambda n, tot, r=row: self.item_progress.emit(r, n, tot or 0),
                                cancel=lambda: self._cancel)
                    ok += 1
                    self.item_done.emit(row, True, out)
                except CancelledError:
                    self.item_done.emit(row, False, "已取消")
                except Exception as e:
                    self.item_done.emit(row, False, str(e).splitlines()[0])
        finally:
            if analyzer is not None:
                analyzer.close()
            self.all_done.emit(ok, len(self.jobs), time.perf_counter() - t0)


# --------------------------------------------------------------------------- main window
def _slider(lo: int, hi: int, val: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    return s


class MainWindow(QMainWindow):
    thumb_ready = Signal(str, bytes)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("视频调色 · 精修")
        self.resize(1440, 900)
        self.setAcceptDrops(True)
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
    def _build_queue(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 4, 8)
        v.addWidget(QLabel("视频队列"))
        self.queue = QListWidget()
        self.queue.currentRowChanged.connect(self._on_select)
        v.addWidget(self.queue, 1)
        row = QHBoxLayout()
        for text, fn in (("添加视频", self._add_files), ("添加文件夹", self._add_folder),
                         ("移除", self._remove_selected)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        return w

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

    def _build_params(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(290)
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 8, 8, 8)

        g = QGroupBox("我的预设")
        gv = QVBoxLayout(g)
        row = QHBoxLayout()
        self.preset_box = QComboBox()
        self.preset_box.setPlaceholderText("（无）")
        b_apply = QPushButton("应用")
        b_apply.clicked.connect(self._apply_preset)
        row.addWidget(self.preset_box, 1)
        row.addWidget(b_apply)
        gv.addLayout(row)
        row = QHBoxLayout()
        for text, fn in (("存为预设", self._save_preset), ("删除预设", self._delete_preset),
                         ("应用到全部", self._apply_to_all)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        gv.addLayout(row)
        v.addWidget(g)
        self._reload_presets()

        g = QGroupBox("风格")
        f = QFormLayout(g)
        self.style_box = QComboBox()
        for st in list_styles():
            self.style_box.addItem(st.title or st.name, st.name)
        self.style_box.setCurrentIndex(max(0, self.style_box.findData("film_warm")))
        self.style_box.currentIndexChanged.connect(self.param_timer.start)
        self.strength = _slider(0, 150, 100)
        self.strength_lbl = QLabel()
        f.addRow("风格", self.style_box)
        self.ref_thumb = QLabel()
        f.addRow(self.ref_thumb)
        self.ref_button = QPushButton("\u53c2\u8003\u56fe\u8ffd\u8272")
        self.ref_button.clicked.connect(self._choose_reference)
        f.addRow(self.ref_button)
        self.skin_protect = _slider(0, 100, 80)
        self.skin_lbl = QLabel()
        f.addRow(self._labeled("\u80a4\u8272\u4fdd\u62a4", self.skin_protect, self.skin_lbl))
        self.style_box.currentIndexChanged.connect(self._style_changed)
        self.skin_protect.valueChanged.connect(self.param_timer.start)
        self.skin_protect.valueChanged.connect(self._update_labels)
        self._style_changed()
        f.addRow(self._labeled("强度", self.strength, self.strength_lbl))
        v.addWidget(g)

        g = QGroupBox("人像精修")
        f = QFormLayout(g)
        self.retouch = _slider(0, 100, 50)
        self.spots = _slider(0, 100, 80)
        self.eyes = _slider(0, 100, 45)
        self.retouch_lbl, self.spots_lbl, self.eyes_lbl = QLabel(), QLabel(), QLabel()
        self.keep_moles = QCheckBox("保留痣")
        self.keep_moles.setChecked(True)
        self.debug = QCheckBox("标出检测（红=痘 / 蓝=黑眼圈）")
        f.addRow(self._labeled("磨皮美颜", self.retouch, self.retouch_lbl))
        f.addRow(self._labeled("祛痘淡斑", self.spots, self.spots_lbl))
        f.addRow(self._labeled("黑眼圈", self.eyes, self.eyes_lbl))
        f.addRow(self.keep_moles)
        f.addRow(self.debug)
        v.addWidget(g)
        self.spots.sliderMoved.connect(lambda _: setattr(self, "spots_touched", True))
        self.eyes.sliderMoved.connect(lambda _: setattr(self, "eyes_touched", True))
        self.retouch.valueChanged.connect(self._follow_retouch)
        for s in (self.strength, self.retouch, self.spots, self.eyes):
            s.valueChanged.connect(self.param_timer.start)
            s.valueChanged.connect(self._update_labels)
        for c in (self.keep_moles, self.debug):
            c.toggled.connect(self.param_timer.start)
        self._update_labels()

        g = QGroupBox("导出")
        gv = QVBoxLayout(g)
        row = QHBoxLayout()
        self.out_dir = QLineEdit()
        self.out_dir.setPlaceholderText("默认：视频所在文件夹\\cake_out")
        b = QPushButton("…")
        b.setFixedWidth(32)
        b.clicked.connect(self._choose_out)
        row.addWidget(self.out_dir, 1)
        row.addWidget(b)
        gv.addLayout(row)
        row = QHBoxLayout()
        self.export_one = QPushButton("导出当前")
        self.export_all = QPushButton("全部导出")
        self.export_all.setObjectName("primary")
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setEnabled(False)
        self.export_one.clicked.connect(lambda: self._export(all_items=False))
        self.export_all.clicked.connect(lambda: self._export(all_items=True))
        self.cancel_btn.clicked.connect(self._cancel_export)
        for b in (self.export_one, self.export_all, self.cancel_btn):
            row.addWidget(b)
        gv.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.export_status = QLabel("")
        self.export_status.setWordWrap(True)
        self.open_out = QPushButton("打开输出文件夹")
        self.open_out.setEnabled(False)
        self.open_out.clicked.connect(lambda: os.startfile(self.last_out_dir))
        gv.addWidget(self.progress)
        gv.addWidget(self.export_status)
        gv.addWidget(self.open_out)
        v.addWidget(g)
        v.addStretch(1)
        self.info_lbl = QLabel("")
        self.info_lbl.setWordWrap(True)
        self.info_lbl.setStyleSheet("color:#7d828a; font-size:12px;")
        v.addWidget(self.info_lbl)
        return w

    @staticmethod
    def _labeled(name: str, slider: QSlider, value_lbl: QLabel) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(name)
        lbl.setFixedWidth(60)
        value_lbl.setFixedWidth(36)
        value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(lbl)
        h.addWidget(slider, 1)
        h.addWidget(value_lbl)
        return w

    # ---------------------------------------------------------------- params
    def _choose_reference(self):
        item = self.queue.currentItem()
        if item is None:
            self.statusBar().showMessage("\u8bf7\u5148\u9009\u62e9\u89c6\u9891")
            return
        ref, _ = QFileDialog.getOpenFileName(self, "\u9009\u62e9\u53c2\u8003\u56fe", "", "\u56fe\u7247 (*.jpg *.jpeg *.png *.webp *.bmp)")
        if not ref:
            return
        self.ref_button.setEnabled(False)
        self.statusBar().showMessage("\u6b63\u5728\u751f\u6210\u53c2\u8003\u56fe\u98ce\u683c...")
        self.ref_worker = ReferenceWorker(ref, item.data(ROLE_PATH))
        self.ref_worker.ready.connect(self._reference_ready)
        self.ref_worker.failed.connect(lambda err: self.statusBar().showMessage("\u751f\u6210\u5931\u8d25: " + err))
        self.ref_worker.finished.connect(lambda: self.ref_button.setEnabled(True))
        self.ref_worker.start()

    def _reference_ready(self, name, title):
        idx = self.style_box.findData(name)
        if idx < 0:
            self.style_box.addItem(title, name)
            idx = self.style_box.findData(name)
        self.style_box.setCurrentIndex(idx)
        self._style_changed()
        self.statusBar().showMessage("\u53c2\u8003\u56fe\u98ce\u683c\u5df2\u751f\u6210")

    def _style_changed(self):
        st = load_style(self.style_box.currentData())
        self.skin_protect.setEnabled(bool(st.skin_lut))
        pix = QPixmap(st.reference) if st.reference else QPixmap()
        self.ref_thumb.setPixmap(pix.scaled(160, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _follow_retouch(self, v: int):
        r = v / 100
        if not self.spots_touched:
            self.spots.setValue(round(min(1.0, 1.6 * r) * 100))
        if not self.eyes_touched:
            self.eyes.setValue(round(min(0.8, 0.9 * r) * 100))

    def _update_labels(self):
        self.skin_lbl.setText(f"{self.skin_protect.value()}%")
        self.strength_lbl.setText(f"{self.strength.value()}%")
        self.retouch_lbl.setText(str(self.retouch.value()))
        self.spots_lbl.setText(str(self.spots.value()))
        self.eyes_lbl.setText(str(self.eyes.value()))

    def settings(self) -> dict:
        return {"style": self.style_box.currentData(), "strength": self.strength.value() / 100,
                "skin_protect": self.skin_protect.value() / 100,
                "retouch": self.retouch.value() / 100,
                "opts": {"spots": self.spots.value() / 100, "under": self.eyes.value() / 100,
                         "keep_moles": self.keep_moles.isChecked(), "debug": False}}

    def _send_params(self):
        s = self.settings()
        self.engine.set_params(style=s["style"], strength=s["strength"], retouch=s["retouch"],
                               skin_protect_scale=s["skin_protect"] / .8, spots=s["opts"]["spots"], eyes=s["opts"]["under"],
                               keep_moles=s["opts"]["keep_moles"], debug=self.debug.isChecked())
        it = self.queue.currentItem()
        if it is not None and not self._applying:
            it.setData(ROLE_SETTINGS, s)          # every clip remembers its own settings

    def apply_settings(self, s: dict):
        """Push a settings dict into the widgets (one engine update at the end)."""
        self._applying = True
        try:
            self.style_box.setCurrentIndex(max(0, self.style_box.findData(s["style"])))
            self.strength.setValue(round(s["strength"] * 100))
            self.retouch.setValue(round(s["retouch"] * 100))
            self.skin_protect.setValue(round(s.get("skin_protect", .8) * 100))
            self.spots.setValue(round(s["opts"]["spots"] * 100))
            self.eyes.setValue(round(s["opts"]["under"] * 100))
            self.keep_moles.setChecked(s["opts"]["keep_moles"])
            self.spots_touched = self.eyes_touched = True
        finally:
            self._applying = False
        self.param_timer.stop()
        self._send_params()

    # ---------------------------------------------------------------- presets
    def _reload_presets(self, select: str | None = None):
        self.presets = load_presets()
        self.preset_box.clear()
        for name in self.presets:
            self.preset_box.addItem(name)
        if select:
            self.preset_box.setCurrentText(select)

    def _save_preset(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "存为预设", "预设名称：",
                                        text=self.style_box.currentText())
        if ok and name.strip():
            self.presets[name.strip()] = self.settings()
            save_presets(self.presets)
            self._reload_presets(select=name.strip())
            self.statusBar().showMessage(f"已保存预设「{name.strip()}」")

    def _apply_preset(self):
        s = self.presets.get(self.preset_box.currentText())
        if s:
            self.apply_settings(s)

    def _delete_preset(self):
        name = self.preset_box.currentText()
        if name in self.presets:
            del self.presets[name]
            save_presets(self.presets)
            self._reload_presets()

    def _apply_to_all(self):
        s = self.settings()
        for r in range(self.queue.count()):
            self.queue.item(r).setData(ROLE_SETTINGS, s)
        self.statusBar().showMessage(f"当前参数已应用到全部 {self.queue.count()} 段视频")

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
    def add_paths(self, paths):
        first_new = None
        for p in paths:
            p = Path(p)
            files = sorted(f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXT) if p.is_dir() else [p]
            for f in files:
                if f.suffix.lower() not in VIDEO_EXT:
                    continue
                it = QListWidgetItem(f.name)
                it.setData(ROLE_PATH, str(f))
                it.setData(ROLE_SETTINGS, self.settings())   # new clips start from current settings
                it.setToolTip(str(f))
                self.queue.addItem(it)
                first_new = first_new if first_new is not None else self.queue.count() - 1
                threading.Thread(target=lambda p=str(f): self._make_thumb(p), daemon=True).start()
        if first_new is not None and self.queue.currentRow() < 0:
            self.queue.setCurrentRow(first_new)

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "添加视频", "", "视频 (*.mp4 *.mov *.m4v *.mkv *.avi)")
        self.add_paths(files)

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "添加文件夹")
        if d:
            self.add_paths([d])

    def _remove_selected(self):
        r = self.queue.currentRow()
        if r >= 0:
            self.queue.takeItem(r)

    def _make_thumb(self, path: str):
        data = _thumbnail(path)
        if data:
            self.thumb_ready.emit(path, data)

    def _set_thumb(self, path: str, data: bytes):
        pm = QPixmap()
        if not pm.loadFromData(data):
            return
        for r in range(self.queue.count()):
            it = self.queue.item(r)
            if it.data(ROLE_PATH) == path:
                it.setIcon(QIcon(pm))
        self.queue.setIconSize(pm.size().boundedTo(pm.size()))

    def _on_select(self, row: int):
        if row < 0:
            return
        it = self.queue.item(row)
        s = it.data(ROLE_SETTINGS)
        if s:
            self.apply_settings(s)                 # restore this clip's own settings
        self.engine.load(it.data(ROLE_PATH))

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
        super().closeEvent(e)


def _mmss(t: float) -> str:
    t = max(0, int(t))
    return f"{t // 60:02d}:{t % 60:02d}"


# --------------------------------------------------------------------------- entry
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cake ui")
    ap.add_argument("videos", nargs="*")
    ap.add_argument("--t", type=float, default=0.0, help="打开后跳到的时间（秒）")
    ap.add_argument("--style")
    ap.add_argument("--retouch", type=float)
    ap.add_argument("--split", type=float)
    ap.add_argument("--mode", choices=["split", "effect", "original"])
    ap.add_argument("--debug-overlay", action="store_true")
    ap.add_argument("--play", type=float, default=0.0, help="自动播放 N 秒（测试用）")
    ap.add_argument("--screenshot", help="自动截图后退出（测试用）")
    ap.add_argument("--export-test", help="导出全部到该文件夹后截图退出（测试用）")
    a = ap.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(QSS)
    win = MainWindow()
    if a.style:
        win.style_box.setCurrentIndex(max(0, win.style_box.findData(a.style)))
    if a.retouch is not None:
        win.retouch.setValue(round(a.retouch * 100))
    if a.split is not None:
        win.view.split = a.split
    if a.mode:
        win.mode_box.setCurrentIndex(win.mode_box.findData(a.mode))
    if a.debug_overlay:
        win.debug.setChecked(True)
    win.show()
    if a.videos:
        win.add_paths(a.videos)
        if a.t:
            QTimer.singleShot(300, lambda: win.engine.seek(a.t))
    if a.screenshot or a.export_test:
        _automate(app, win, a)
    return app.exec()


def _automate(app, win: MainWindow, a):
    """Test driver: wait for frames, optionally play / export, grab the window, quit."""
    start = time.perf_counter()
    state = {"phase": "wait_frame", "t": 0.0, "frames0": 0}

    def tick():
        now = time.perf_counter()
        if now - start > 120:
            print("automation timeout", flush=True)
            app.quit()
            return
        if state["phase"] == "wait_frame":
            if win.frames_seen >= (2 if a.t else 1):
                state.update(phase="settle", t=now)
        elif state["phase"] == "settle" and now - state["t"] > 1.5:
            if a.play:
                state.update(phase="playing", t=now, frames0=win.frames_seen)
                win.engine.play()
            elif a.export_test:
                win.out_dir.setText(a.export_test)
                win._export(all_items=True)
                state.update(phase="exporting", t=now)
            else:
                state["phase"] = "shoot"
        elif state["phase"] == "playing" and now - state["t"] > a.play:
            win.engine.pause()
            n = win.frames_seen - state["frames0"]
            print(f"played {n} frames in {now - state['t']:.1f}s = {n / (now - state['t']):.1f} fps",
                  flush=True)
            state.update(phase="settle2", t=now)
        elif state["phase"] == "settle2" and now - state["t"] > 0.5:
            state["phase"] = "shoot"
        elif state["phase"] == "exporting" and win.export_worker is None:
            print("export:", win.export_status.text(), flush=True)
            state["phase"] = "shoot"
        if state["phase"] == "shoot":
            out = a.screenshot or str(Path(a.export_test) / "ui_after_export.png")
            win.grab().save(out)
            print("screenshot", out, flush=True)
            state["phase"] = "done"
            win.close()
            app.quit()

    timer = QTimer(win, interval=100)
    timer.timeout.connect(tick)
    timer.start()


if __name__ == "__main__":
    sys.exit(main())
