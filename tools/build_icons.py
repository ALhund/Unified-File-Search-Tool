"""アプリアイコン（assets/app.svg）から .ico / .png を生成する

使い方: uv run python tools/build_icons.py

16〜32px は細部がつぶれないよう、簡略版（assets/app-small.svg）から描く。
.ico の書き出しには Pillow を使う（開発時のみ必要）。
"""

import io
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parents[1] / "assets"
SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
SMALL_LIMIT = 32


def render(svg_path: Path, size: int) -> bytes:
    renderer = QSvgRenderer(str(svg_path))
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def main() -> int:
    from PIL import Image
    
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    
    images = {}
    for size in SIZES:
        source = ASSETS / ("app-small.svg" if size <= SMALL_LIMIT else "app.svg")
        images[size] = render(source, size)
    
    (ASSETS / "app-256.png").write_bytes(images[256])
    (ASSETS / "app-48.png").write_bytes(images[48])
    
    frames = [Image.open(io.BytesIO(images[size])).convert("RGBA") for size in SIZES]
    frames[-1].save(
        ASSETS / "app.ico",
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=frames[:-1],
    )
    print("generated:", ", ".join(p.name for p in sorted(ASSETS.glob("app*"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
