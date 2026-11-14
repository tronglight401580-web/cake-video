from __future__ import annotations
import time
from pathlib import Path
from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget
from ..core.recipe import Recipe
from ..styles import load_style
from ..core.bus import bus

class ExportWorker(QThread):
    item_started = Signal(int, str)
    item_progress = Signal(int, int, int)      # row, done, total
    item_done = Signal(int, bool, str)
    all_done = Signal(int, int, float)         # ok, total, seconds

    def __init__(self, jobs: list[tuple[int, str, Recipe | dict]], out_dir: str):
        """jobs: (queue row, path, that clip's own settings)."""
        super().__init__()
        self.jobs = [(row, path, s if isinstance(s, Recipe) else Recipe.from_dict(s)
                      if isinstance(s.get('retouch'), dict) else Recipe.from_legacy(s))
                     for row, path, s in jobs]
        self.out_dir = out_dir
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
            if any(s.retouch.level > 0 or (load_style(s.style).skin_lut and load_style(s.style).skin_protect > 0) for _, _, s in self.jobs):
                from ..face import Analyzer
                analyzer = Analyzer()             # one warm pool for the whole batch
            for row, path, s in self.jobs:
                if self._cancel:
                    break
                st = load_style(s.style)
                self.item_started.emit(row, Path(path).name)
                out = str(Path(self.out_dir) / f"{Path(path).stem}_{st.name}.mp4")
                try:
                    grade_video(path, out, recipe=s.for_export(), log=lambda *a: None,
                                analyzer=analyzer,
                                progress=lambda n, tot, r=row: self.item_progress.emit(r, n, tot or 0),
                                cancel=lambda: self._cancel)
                    ok += 1
                    self.item_done.emit(row, True, out)
                except CancelledError:
                    self.item_done.emit(row, False, "已取消")
                except Exception as e:
                    bus.publish('error', message=str(e), input=path)
                    self.item_done.emit(row, False, str(e).splitlines()[0])
        finally:
            if analyzer is not None:
                analyzer.close()
            self.all_done.emit(ok, len(self.jobs), time.perf_counter() - t0)
