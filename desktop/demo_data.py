"""Build synthetic desktop-library data inside a TemporaryDirectory only."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


def _assert_under(root: Path, *paths: Path) -> None:
    root = root.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if root != temp_root and temp_root not in root.parents:
        raise RuntimeError("Demo storage must be inside the system temporary directory.")
    for path in paths:
        resolved = Path(path).resolve()
        if resolved != root and root not in resolved.parents:
            raise RuntimeError(f"Demo path is outside its temporary directory: {path}")


def _cover(destination: Path, index: int) -> None:
    """Create an abstract geometric cover; intentionally draw no text."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPolygonF, QImage

    colors = (
        ("#315a55", "#7fb2a4", "#e5c98a"),
        ("#6c4c76", "#c27e91", "#e8b77e"),
        ("#344f77", "#6e9cbb", "#d7d2a4"),
        ("#66533f", "#b6845c", "#e3c78e"),
        ("#3e665b", "#8fb57c", "#d3d78f"),
        ("#625079", "#9b84b7", "#e1b2c0"),
        ("#3d6476", "#75aeb1", "#e6c487"),
        ("#735549", "#c28169", "#e6c27c"),
    )
    dark, mid, light = colors[(index - 1) % len(colors)]
    image = QImage(400, 400, QImage.Format.Format_ARGB32_Premultiplied)
    gradient = QLinearGradient(0, 0, 400, 400)
    gradient.setColorAt(0, QColor(dark))
    gradient.setColorAt(0.56, QColor(mid))
    gradient.setColorAt(1, QColor(light))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillRect(image.rect(), gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 58))
    painter.drawEllipse(QPointF(318, 82), 180, 180)
    painter.setBrush(QColor(16, 28, 38, 54))
    painter.drawEllipse(QPointF(75, 330), 170, 170)
    painter.setBrush(QColor(255, 255, 255, 105))
    path = QPainterPath()
    path.moveTo(40, 226)
    path.cubicTo(100, 112, 212, 330, 360, 144)
    path.cubicTo(292, 300, 170, 180, 40, 226)
    painter.drawPath(path)
    painter.setBrush(QColor(255, 255, 255, 74))
    painter.drawPolygon(QPolygonF([QPointF(70, 64), QPointF(118, 38), QPointF(148, 100), QPointF(98, 132)]))
    painter.end()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(destination), "PNG"):
        raise RuntimeError(f"Could not create synthetic cover: {destination.name}")


def seed(root: Path, stack):
    """Patch every mutable runtime path and seed eight fictional tracks."""
    import app
    import auth
    import music_covers
    import music_export as m
    import runtime_paths
    import settings

    root = Path(root).resolve()
    data = Path(os.environ["MUSIC_DATA_DIR"]).resolve()
    if data != root and root not in data.parents:
        raise RuntimeError("MUSIC_DATA_DIR must point inside the demo TemporaryDirectory.")
    music_dir = data / "music"
    account_dir = music_dir / "account_demo"
    cover_dir = data / "cover_cache"
    paths = (
        data,
        music_dir,
        account_dir,
        data / "music_state.db",
        data / "music_status.json",
        data / "STOP_MUSIC",
        data / "settings.json",
        data / "relocation.json",
        data / "auth_private.json",
        data / "device_private.json",
        data / "cover_cache",
    )
    _assert_under(root, *paths)

    for owner, name, value in (
        (runtime_paths, "DATA", data),
        (auth, "DATA", data),
        (auth, "AUTH", data / "auth_private.json"),
        (auth, "DEVICE", data / "device_private.json"),
        (settings, "CONFIG", data / "settings.json"),
        (settings, "MOVE", data / "relocation.json"),
        (m, "DATA", data),
        (m, "DB", data / "music_state.db"),
        (m, "STATUS", data / "music_status.json"),
        (m, "STOP", data / "STOP_MUSIC"),
        (m, "DEST", music_dir),
        (music_covers, "CACHE", cover_dir),
    ):
        stack.enter_context(patch.object(owner, name, value))

    stack.enter_context(patch.object(app, "running", return_value=False))
    stack.enter_context(patch.object(app.Window, "check_account", lambda self: None))
    stack.enter_context(patch.object(app.Window, "make_tray", lambda self: setattr(self, "tray", None)))
    for method in ("get", "post", "request"):
        stack.enter_context(patch.object(m.requests, method, side_effect=RuntimeError("Network access is disabled for synthetic screenshots.")))

    _assert_under(root, auth.AUTH, auth.DEVICE, settings.CONFIG, settings.MOVE, m.DB, m.STATUS, m.STOP, m.DEST, music_covers.CACHE)
    data.mkdir(parents=True, exist_ok=True)
    music_dir.mkdir(parents=True, exist_ok=True)
    account_dir.mkdir(parents=True, exist_ok=True)
    settings.save({
        "destination": str(music_dir),
        "theme": "dark",
        "auto_sync": False,
        "wifi_only": False,
        "account_name": "Демо",
        "auto_hours": 6,
    })
    auth.AUTH.write_text(
        json.dumps({"access_token": "fixture-only-not-a-token", "account": {"name": "Демо"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    m.initialize()
    rows = (
        ("01", "downloaded", 1, True),
        ("02", "downloaded", 1, True),
        ("03", "downloaded", 1, True),
        ("04", "pending", 1, False),
        ("05", "unavailable", 1, False),
        ("06", "failed", 1, False),
        ("07", "downloaded", 0, True),
        ("08", "failed", 0, False),
    )
    cover_dir.mkdir(parents=True, exist_ok=True)
    with m.db() as connection:
        connection.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('uid','demo-account')")
        connection.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_sync','0')")
        for index, (ident, status, liked, downloaded) in enumerate(rows, start=1):
            title = f"Трек{index:02d}"
            artist = f"Демо-артист{index:02d}"
            album = f"Альбом{index:02d}"
            cover_uri = f"avatars.yandex.net/demo-cover-{index:02d}/%%"
            cover_url = f"https://avatars.yandex.net/demo-cover-{index:02d}/400x400"
            cover_path = cover_dir / (hashlib.sha256(cover_url.encode("utf-8")).hexdigest() + ".image")
            _cover(cover_path, index)

            path = None
            size = None
            sha256 = None
            if downloaded:
                path = account_dir / f"{title}.mp3"
                audio_fixture = (f"DEMO-ONLY PLACEHOLDER AUDIO {ident}\n").encode("ascii")
                path.write_bytes(audio_fixture)
                size = len(audio_fixture)
                sha256 = hashlib.sha256(audio_fixture).hexdigest()

            error = {
                "unavailable": "Демо-запись недоступна",
                "failed": "Демо-ошибка загрузки",
            }.get(status)
            connection.execute(
                """INSERT INTO tracks(
                    id,position,title,artist,album,year,duration_ms,available,status,path,size,sha256,bitrate,error,
                    cover_uri,cover_status,lyrics_available,lyrics_sync,lyrics_status,liked,archive_hidden
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                (
                    ident, index - 1, title, artist, album, "2026", 135000 + index * 1000,
                    0 if status == "unavailable" else 1, status, str(path) if path else None, size, sha256,
                    320000 if downloaded else None, error, cover_uri,
                    "done" if downloaded else "pending", 0, 0, "unavailable", liked,
                ),
            )
    return app
