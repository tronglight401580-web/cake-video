"""UI regression test (offscreen): load, live parameter change while paused, seek, export cancel.

    python tools/test_ui.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def wait(app, cond, timeout=60.0, what=""):
    t0 = time.perf_counter()
    while not cond():
        app.processEvents()
        time.sleep(0.02)
        if time.perf_counter() - t0 > timeout:
            raise AssertionError(f"timeout waiting for {what}")
    return time.perf_counter() - t0


def main():
    from PySide6.QtWidgets import QApplication
    from cake.ui.app import MainWindow
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    clips = [str(ROOT / "samples" / n) for n in
             ("asian_hush_48036.mp4", "asian_mother_child_48689.mp4", "street_mixed_1227.mp4")]
    win.add_paths(clips)
    dt = wait(app, lambda: win.frames_seen >= 1, 90, "first frame")
    print(f"first frame after {dt:.1f}s (includes retouch model start-up)")

    # live parameter change while paused -> one re-rendered frame, quickly
    n0, img0 = win.frames_seen, win.view.graded
    t0 = time.perf_counter()
    win.style_box.setCurrentIndex(win.style_box.findData("ccd"))
    wait(app, lambda: win.frames_seen > n0, 10, "re-render after style change")
    print(f"style change -> new frame in {(time.perf_counter() - t0) * 1000:.0f} ms")
    assert win.view.graded != img0, "image did not change after style change"
    n0 = win.frames_seen
    t0 = time.perf_counter()
    win.strength.setValue(40)
    wait(app, lambda: win.frames_seen > n0, 10, "re-render after strength change")
    print(f"strength change -> new frame in {(time.perf_counter() - t0) * 1000:.0f} ms")

    # seek while paused
    n0 = win.frames_seen
    win.timeline.setValue(600)
    win._do_seek()
    wait(app, lambda: win.frames_seen > n0, 15, "frame after seek")
    t_label = win.time_label.text()
    print("after seek:", t_label)
    assert t_label.startswith("00:06"), t_label

    # switch clip in the queue
    n0 = win.frames_seen
    win.queue.setCurrentRow(2)
    wait(app, lambda: win.frames_seen > n0 and win.view.graded.height() > win.view.graded.width(),
         30, "portrait clip loaded")
    print("switched to portrait clip:", win.view.graded.width(), "x", win.view.graded.height())

    # export + cancel: no partial file left behind
    out = Path(tempfile.mkdtemp(prefix="cake_ui_"))
    win.out_dir.setText(str(out))
    win._export(all_items=True)
    wait(app, lambda: win.progress.value() > 0, 60, "export progress")
    win._cancel_export()
    wait(app, lambda: win.export_worker is None, 60, "export cancelled")
    left = list(out.glob("*.mp4"))
    print("after cancel:", win.export_status.text(), "| files:", [p.name for p in left])
    assert not any("street" in p.name for p in left), "partial file left behind"
    win.close()
    print("UI test passed")


if __name__ == "__main__":
    main()
