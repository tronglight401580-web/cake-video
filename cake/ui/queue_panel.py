from __future__ import annotations
import subprocess
import threading
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QFileDialog
from ..core.recipe import Recipe

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi"}
ROLE_PATH = Qt.ItemDataRole.UserRole
ROLE_SETTINGS = Qt.ItemDataRole.UserRole + 1

def _thumbnail(path: str, height: int = 56) -> bytes | None:
    """One small JPEG frame for the queue icon (ffmpeg, ~50 ms)."""
    try:
        return subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", path, "-frames:v", "1",
                               "-vf", f"scale=-2:{height}", "-f", "image2pipe", "-c:v", "mjpeg", "-"],
                              capture_output=True, timeout=20).stdout or None
    except (OSError, subprocess.TimeoutExpired):
        return None


class QueuePanel:
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

