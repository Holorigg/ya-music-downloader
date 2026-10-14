"""Render synthetic, fully offline desktop screenshots for the README."""
from __future__ import annotations

import os
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

from demo_data import seed


WIDTH = 1120
HEIGHT = 800


def wait_for(application, predicate, seconds: float, message: str) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    raise RuntimeError(message)


def render(application, window, settings, mode: str, destination: Path) -> None:
    from PySide6.QtCore import QSize

    settings.save({"theme": mode})
    window.resize(WIDTH, HEIGHT)
    window.apply_theme()
    window.refresh()
    application.processEvents()
    if window.size() != QSize(WIDTH, HEIGHT):
        raise RuntimeError(f"Expected {WIDTH}x{HEIGHT}, got {window.width()}x{window.height()}.")
    pixmap = window.grab()
    if pixmap.size() != QSize(WIDTH, HEIGHT):
        raise RuntimeError("The rendered desktop screenshot has an unexpected size.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not pixmap.save(str(destination), "PNG"):
        raise RuntimeError(f"Could not write screenshot: {destination}")


def main() -> int:
    # The variable is set before runtime_paths/auth/app are imported. All mutable
    # state, the fixture MP3 files, and cover cache stay under this temp root.
    with tempfile.TemporaryDirectory(prefix="ya-music-demo-") as temporary:
        root = Path(temporary).resolve()
        os.environ["MUSIC_DATA_DIR"] = str(root / "data")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["QT_SCALE_FACTOR"] = "1"

        from PySide6.QtGui import QFont, QFontDatabase
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance() or QApplication([])
        application.setQuitOnLastWindowClosed(False)
        for font in (Path(r"C:\Windows\Fonts\segoeui.ttf"), Path(r"C:\Windows\Fonts\seguisb.ttf")):
            if font.is_file():
                QFontDatabase.addApplicationFont(str(font))
        application.setFont(QFont("Segoe UI", 10))

        with ExitStack() as stack:
            app_module = seed(root, stack)
            window = app_module.Window()
            window.resize(WIDTH, HEIGHT)
            window.show()
            wait_for(application, lambda: not window.snapshot_pending, 8, "Timed out loading synthetic demo rows.")
            if not window.model.rows:
                raise RuntimeError("The synthetic demo library is empty.")

            selected = next((i for i, row in enumerate(window.model.rows) if row["id"] == "01"), None)
            if selected is None:
                raise RuntimeError("The synthetic selected track was not found.")
            window.list.setCurrentIndex(window.model.index(selected, 0))
            application.processEvents()
            row = window.selected_row
            if not row or row.get("title") != "Трек01" or row.get("artist") != "Демо-артист01" or row.get("album") != "Альбом01":
                raise RuntimeError("The selected detail panel is not showing the synthetic fixture.")
            artwork_key = window.artwork.key(row)
            wait_for(application, lambda: artwork_key in window.artwork.images, 5, "Timed out loading the local synthetic cover.")

            screenshots = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
            render(application, window, app_module.settings, "dark", screenshots / "desktop-dark.png")
            render(application, window, app_module.settings, "light", screenshots / "desktop-light.png")
            window.close()
            wait_for(application, lambda: window.closed, 3, "The temporary demo window did not close cleanly.")
            window.deleteLater()
            application.processEvents()

        print(f"Wrote synthetic 1120x800 screenshots to {screenshots}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
