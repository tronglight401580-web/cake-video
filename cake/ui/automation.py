from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from .main_window import MainWindow, QSS

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

