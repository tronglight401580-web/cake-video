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
    from PySide6.QtCore import Qt
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

    # queue thumbnails (background ffmpeg)
    wait(app, lambda: all(not win.queue.item(r).icon().isNull() for r in range(win.queue.count())),
         20, "queue thumbnails")
    print("thumbnails: ok")

    # per-clip settings: clip 0 strength 40, clip 1 keeps its own
    win.queue.setCurrentRow(0)
    wait(app, lambda: win.queue.currentRow() == 0, 5)
    win.strength.setValue(40)
    wait(app, lambda: (win.queue.item(0).data(Qt.ItemDataRole.UserRole + 1) or {}).get("strength") == 0.4,
         5, "clip 0 settings stored")
    win.queue.setCurrentRow(1)
    wait(app, lambda: win.strength.value() == 100, 5, "clip 1 own strength")
    win.queue.setCurrentRow(0)
    wait(app, lambda: win.strength.value() == 40, 5, "clip 0 strength restored")
    print("per-clip settings: ok")

    # frame step (paused)
    wait(app, lambda: win.frames_seen > 0, 30)
    time.sleep(1.0)
    app.processEvents()
    n0 = win.frames_seen
    win.engine.step(+1)
    wait(app, lambda: win.frames_seen > n0, 10, "frame step")
    print("frame step: ok")

    # presets (written to a temp file, not the user's real presets)
    import cake.ui.app as appmod
    appmod.PRESETS_FILE = Path(tempfile.mkdtemp(prefix="cake_presets_")) / "presets.json"
    win.style_box.setCurrentIndex(win.style_box.findData("ccd"))
    win.presets = {"测试预设": win.settings()}
    appmod.save_presets(win.presets)
    win.style_box.setCurrentIndex(win.style_box.findData("film_warm"))
    win._reload_presets(select="测试预设")
    win._apply_preset()
    assert win.style_box.currentData() == "ccd", win.style_box.currentData()
    win._apply_to_all()
    assert all((win.queue.item(r).data(Qt.ItemDataRole.UserRole + 1) or {}).get("style") == "ccd"
               for r in range(win.queue.count()))
    print("presets + apply-to-all: ok")

    # export one clip fully: output complete, 'open folder' enabled
    out1 = Path(tempfile.mkdtemp(prefix="cake_ui1_"))
    win.out_dir.setText(str(out1))
    win.queue.setCurrentRow(1)
    win._export(all_items=False)
    wait(app, lambda: win.export_worker is None, 180, "single export")
    files = list(out1.glob("*.mp4"))
    assert len(files) == 1 and win.open_out.isEnabled(), (files, win.export_status.text())
    import subprocess
    nb = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                         "stream=nb_frames", "-of", "csv=p=0", str(files[0])],
                        capture_output=True, text=True).stdout.strip()
    print("single export:", win.export_status.text(), "| frames", nb)
    assert nb == "185", nb

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
