"""アイコン

すべてこのアプリ用に描いたSVG（24×24、線幅1.7の線画）。色はテーマから与えるので、
ライト/ダーク・アクセント色の変更に追従し、高DPIでもにじまない。
"""

import hashlib
import tempfile
import weakref
from functools import lru_cache
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QApplication

from src.common.paths import resource_dir

ASSETS_DIR = resource_dir() / "assets"

_STROKE = (
    'fill="none" stroke="{c}" stroke-width="1.7" '
    'stroke-linecap="round" stroke-linejoin="round"'
)

# 名前 → SVGの中身（{c} が色に置き換わる）
_ICONS: dict[str, str] = {
    "search": '<circle cx="10.5" cy="10.5" r="6.3"/><path d="M15.3 15.3L20 20"/>',
    "folder": '<path d="M3.5 7.5a2 2 0 0 1 2-2h3.8l2.2 2.2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "folder-open": (
        '<path d="M3.5 17V7.5a2 2 0 0 1 2-2h3.8l2.2 2.2h6a2 2 0 0 1 2 2v1"/>'
        '<path d="M3.6 17.6l2.2-5.8a1.6 1.6 0 0 1 1.5-1h12.4a1 1 0 0 1 .95 1.32l-1.9 5.7'
        'a1.6 1.6 0 0 1-1.5 1.1H5a1.4 1.4 0 0 1-1.4-1.3z"/>'
    ),
    "chevron-down": '<path d="M6.5 9.5l5.5 5.5 5.5-5.5"/>',
    "chevron-up": '<path d="M6.5 14.5l5.5-5.5 5.5 5.5"/>',
    "chevron-left": '<path d="M14.5 6.5L9 12l5.5 5.5"/>',
    "chevron-right": '<path d="M9.5 6.5L15 12l-5.5 5.5"/>',
    "close": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    "check": '<path d="M5.5 12.5l4.2 4.2L18.5 7.8" stroke-width="2.4"/>',
    "settings": (
        '<path d="M10.3 3.6h3.4l.5 2.3 1.6.9 2.2-.8 1.7 2.9-1.8 1.6v1.9l1.8 1.6-1.7 2.9-2.2-.8'
        '-1.6.9-.5 2.3h-3.4l-.5-2.3-1.6-.9-2.2.8-1.7-2.9 1.8-1.6v-1.9L4.3 8.9 6 6l2.2.8 1.6-.9z"/>'
        '<circle cx="12" cy="12" r="2.8"/>'
    ),
    "sun": (
        '<circle cx="12" cy="12" r="3.8"/><path d="M12 3v1.8M12 19.2V21M3 12h1.8M19.2 12H21'
        'M5.6 5.6l1.3 1.3M17.1 17.1l1.3 1.3M5.6 18.4l1.3-1.3M17.1 6.9l1.3-1.3"/>'
    ),
    "moon": '<path d="M19.5 14.6A7.8 7.8 0 0 1 9.4 4.5a7.8 7.8 0 1 0 10.1 10.1z"/>',
    "case": (
        '<path d="M3 18.5L7.3 6.5h.4l4.3 12M4.6 14.3h5.8"/>'
        '<circle cx="17" cy="15.3" r="3.2"/><path d="M20.2 11.5v7"/>'
    ),
    "width": (
        '<rect x="3" y="6" width="11" height="12" rx="2"/>'
        '<rect x="16.5" y="6" width="4.5" height="12" rx="1.5"/>'
        '<path d="M6 10h5M8.5 10v5"/>'
    ),
    "whole": '<path d="M6 5.5H4v13h2M18 5.5h2v13h-2M8.5 10h7M8.5 14h7"/>',
    "regex": (
        '<circle cx="6" cy="17.5" r="1.6" fill="{c}" stroke="none"/>'
        '<path d="M15 4.5v9M11.1 6.75l7.8 4.5M11.1 11.25l7.8-4.5"/>'
    ),
    "subfolder": (
        '<path d="M5 4v11.5A2.5 2.5 0 0 0 7.5 18H11M5 8.5h6"/>'
        '<rect x="12" y="6" width="8" height="5" rx="1.5"/><rect x="12" y="15.5" width="8" height="5" rx="1.5"/>'
    ),
    "external": (
        '<path d="M13.5 4.5h6v6M19.5 4.5L11 13"/>'
        '<path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>'
    ),
    "copy": (
        '<rect x="8.5" y="8.5" width="11.5" height="11.5" rx="2"/>'
        '<path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5"/>'
    ),
    "zoom-in": '<circle cx="10.5" cy="10.5" r="6.3"/><path d="M15.3 15.3L20 20M10.5 8v5M8 10.5h5"/>',
    "zoom-out": '<circle cx="10.5" cy="10.5" r="6.3"/><path d="M15.3 15.3L20 20M8 10.5h5"/>',
    "fit-width": '<path d="M4 5v14M20 5v14M7.5 12h9M10 9.5L7.5 12l2.5 2.5M14 9.5l2.5 2.5-2.5 2.5"/>',
    "page": (
        '<rect x="5" y="3.5" width="14" height="17" rx="2"/>'
        '<circle cx="9.8" cy="8.8" r="1.4"/><path d="M8 16.5l3-3.3 2.2 2.2 1.6-1.6 2.2 2.7"/>'
    ),
    "text": '<path d="M5 6.5h14M5 10.5h14M5 14.5h14M5 18.5h8.5"/>',
    "history": '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3M4.5 4.5v3.2h3.2"/><path d="M12 8v4.3l2.8 1.8"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="2.2"/>',
    "info": (
        '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5"/>'
        '<circle cx="12" cy="7.9" r="1" fill="{c}" stroke="none"/>'
    ),
    "warning": (
        '<path d="M10.3 5.2a2 2 0 0 1 3.4 0l6.9 11.8a2 2 0 0 1-1.7 3H5.1a2 2 0 0 1-1.7-3z"/>'
        '<path d="M12 9.8v4"/><circle cx="12" cy="16.9" r="1" fill="{c}" stroke="none"/>'
    ),
    "trash": (
        '<path d="M4.5 7h15M9.5 7V5.2a.7.7 0 0 1 .7-.7h3.6a.7.7 0 0 1 .7.7V7"/>'
        '<path d="M6.5 7l.9 11.7a1.8 1.8 0 0 0 1.8 1.6h5.6a1.8 1.8 0 0 0 1.8-1.6L17.5 7M10.2 11v5.5M13.8 11v5.5"/>'
    ),
    "sort": '<path d="M7.5 4.5v15M4.5 16.5l3 3 3-3M16.5 19.5v-15M13.5 7.5l3-3 3 3"/>',
    "filter": '<path d="M4 5.5h16l-6.2 7.2v5.6l-3.6 1.5v-7.1z"/>',
    "sliders": (
        '<path d="M4 7h9.5M17.5 7H20M4 17h2.5M10.5 17H20"/>'
        '<circle cx="15.5" cy="7" r="2"/><circle cx="8.5" cy="17" r="2"/>'
    ),
    "help": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M9.7 9.6a2.4 2.4 0 1 1 3.5 2.1c-.8.4-1.2 1-1.2 1.8v.4"/>'
        '<circle cx="12" cy="16.8" r="1" fill="{c}" stroke="none"/>'
    ),
    "list": (
        '<path d="M9 6.5h11M9 12h11M9 17.5h11"/>'
        '<circle cx="4.8" cy="6.5" r="1.1" fill="{c}" stroke="none"/>'
        '<circle cx="4.8" cy="12" r="1.1" fill="{c}" stroke="none"/>'
        '<circle cx="4.8" cy="17.5" r="1.1" fill="{c}" stroke="none"/>'
    ),
    "layers": '<path d="M12 4l8.5 4.5L12 13 3.5 8.5z"/><path d="M3.5 12.3L12 16.8l8.5-4.5M3.5 16L12 20.5l8.5-4.5"/>',
    "document": (
        '<path d="M7 3.5h7l4.5 4.5v11a1.5 1.5 0 0 1-1.5 1.5H7A1.5 1.5 0 0 1 5.5 19V5A1.5 1.5 0 0 1 7 3.5z"/>'
        '<path d="M13.5 3.5V8h5M8.5 12.5h7M8.5 16h5"/>'
    ),
    "keyboard": (
        '<rect x="2.5" y="6" width="19" height="12" rx="2"/>'
        '<path d="M6 10h.01M9 10h.01M12 10h.01M15 10h.01M18 10h.01M8 14h8" stroke-width="2"/>'
    ),
    "exclude": '<circle cx="12" cy="12" r="8"/><path d="M6.4 17.6L17.6 6.4"/>',
    "hash": '<path d="M9.5 4L7.5 20M16.5 4l-2 16M4.5 9h15M4 15h15"/>',
    "key": '<circle cx="8" cy="15.5" r="4.2"/><path d="M11 12.5l8.5-8.5M16.2 7.3l2.6 2.6M13.8 9.7l2 2"/>',
    "export": '<path d="M12 4v10.5M7.5 10L12 14.5 16.5 10"/><path d="M4.5 15.5v2.5a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-2.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "palette": (
        '<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.1 0 1.7-.9 1.4-1.9-.4-1.3.4-2.6 1.8-2.6H17'
        'a3.5 3.5 0 0 0 3.5-3.5C20.5 7.3 16.7 3.5 12 3.5z"/>'
        '<circle cx="8" cy="11" r="1.1" fill="{c}" stroke="none"/>'
        '<circle cx="10.5" cy="7.5" r="1.1" fill="{c}" stroke="none"/>'
        '<circle cx="15" cy="7.8" r="1.1" fill="{c}" stroke="none"/>'
    ),
    "database": (
        '<ellipse cx="12" cy="6" rx="7" ry="2.5"/>'
        '<path d="M5 6v12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V6M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/>'
    ),
    "speed": '<path d="M4.5 16.5a7.5 7.5 0 1 1 15 0"/><path d="M12 16.5l3.8-5"/><circle cx="12" cy="16.5" r="1.2"/>',
}

# ファイル種類ごとの色と表示ラベル
FILE_TYPES: dict[str, tuple[str, str]] = {
    "xlsx": ("#1F7A4A", "XLS"),
    "xlsm": ("#1F7A4A", "XLSM"),
    "xls": ("#1F7A4A", "XLS"),
    "doc": ("#2B5FB4", "DOC"),
    "ppt": ("#C2511F", "PPT"),
    "docx": ("#2B5FB4", "DOC"),
    "pptx": ("#C2511F", "PPT"),
    "pdf": ("#CF3A2E", "PDF"),
    "txt": ("#5F6670", "TXT"),
    "md": ("#7652C0", "MD"),
    "log": ("#4A5260", "LOG"),
}
DEFAULT_FILE_TYPE = ("#6B7280", "FILE")


def svg(name: str, color: str) -> str:
    body = _ICONS[name].replace("{c}", color)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {_STROKE.format(c=color)}>'
        f"{body}</svg>"
    )


def file_type_svg(extension: str) -> str:
    """ファイル種類のアイコン（色帯つきの書類）"""
    color, label = FILE_TYPES.get(extension.lower(), DEFAULT_FILE_TYPE)
    font_size = 7.2 if len(label) <= 3 else 6.0
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <path d="M8 2.5h11.2L26.5 9.8V28a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4.5a2 2 0 0 1 2-2z"
        fill="#FFFFFF" stroke="#B8BEC6" stroke-width="1"/>
  <path d="M19.2 2.5V8a1.8 1.8 0 0 0 1.8 1.8h5.5" fill="#EEF0F3" stroke="#B8BEC6" stroke-width="1"
        stroke-linejoin="round"/>
  <path d="M10 25.2h12.5M10 27.4h8" stroke="#D5D9DE" stroke-width="1.1" stroke-linecap="round"/>
  <rect x="2.5" y="12.5" width="19.5" height="10" rx="2.2" fill="{color}"/>
  <text x="12.25" y="20.1" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif"
        font-weight="700" font-size="{font_size}" fill="#FFFFFF" letter-spacing="0.2">{label}</text>
</svg>'''


def _render(svg_text: str, size: int, ratio: float) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
    pixels = max(1, round(size * ratio))
    image = QImage(pixels, pixels, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, pixels, pixels))
    painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def _device_ratio() -> float:
    app = QApplication.instance()
    if app is None:
        return 1.0
    screens = app.screens()
    return max([s.devicePixelRatio() for s in screens] + [1.0])


def _palette():
    from src.ui.theme import palette
    return palette()


@lru_cache(maxsize=512)
def _cached_icon(name: str, color: str, on_color: str, disabled_color: str, size: int) -> QIcon:
    ratio = _device_ratio()
    icon = QIcon()
    for scale in sorted({1.0, ratio, 2.0}):
        icon.addPixmap(_render(svg(name, color), size, scale), QIcon.Mode.Normal, QIcon.State.Off)
        icon.addPixmap(_render(svg(name, on_color), size, scale), QIcon.Mode.Normal, QIcon.State.On)
        for state in (QIcon.State.Off, QIcon.State.On):
            icon.addPixmap(_render(svg(name, disabled_color), size, scale), QIcon.Mode.Disabled, state)
    return icon


def icon(name: str, role: str = "text", size: int = 20) -> QIcon:
    """テーマに合わせた色のアイコン
    
    role: text / secondary / accent / on_accent / danger / warning
    """
    p = _palette()
    colors = {
        "text": p.text,
        "secondary": p.text_secondary,
        "accent": p.accent_fg,
        "on_accent": p.accent_text,
        "danger": p.danger,
        "warning": p.warning_text,
    }
    color = colors.get(role, p.text)
    on_color = p.accent_fg if role in ("text", "secondary") else color
    return _cached_icon(name, color, on_color, p.text_tertiary, size)


def pixmap(name: str, color: str, size: int = 20) -> QPixmap:
    return _render(svg(name, color), size, _device_ratio())


@lru_cache(maxsize=64)
def file_icon(extension: str, size: int = 32) -> QIcon:
    icon = QIcon()
    for scale in sorted({1.0, _device_ratio(), 2.0}):
        icon.addPixmap(_render(file_type_svg(extension), size, scale))
    return icon


def file_pixmap(extension: str, size: int = 32) -> QPixmap:
    return file_icon(extension, size).pixmap(QSize(size, size), _device_ratio())


def icon_file(name: str, color: str) -> str:
    """スタイルシートから参照するためのSVGファイルを書き出してパスを返す"""
    folder = Path(tempfile.gettempdir()) / "ufst_icons"
    folder.mkdir(exist_ok=True)
    text = svg(name, color)
    path = folder / f"{name}-{hashlib.md5(text.encode()).hexdigest()[:10]}.svg"
    if not path.exists():
        path.write_text(text, encoding="utf-8")
    return path.as_posix()


def clear_cache() -> None:
    _cached_icon.cache_clear()


# ---------------------------------------------------------------------------
# テーマ変更時にアイコンを貼り直すための登録
# ---------------------------------------------------------------------------

_bound: "weakref.WeakKeyDictionary[QAbstractButton, tuple[str, str, int]]" = weakref.WeakKeyDictionary()


def bind(button: QAbstractButton, name: str, role: str = "text", size: int = 18) -> QAbstractButton:
    """ボタンにアイコンを付け、テーマ変更時に自動で色を更新する"""
    _bound[button] = (name, role, size)
    button.setIcon(icon(name, role, size))
    button.setIconSize(QSize(size, size))
    return button


def rebind(button: QAbstractButton, name: Optional[str] = None, role: Optional[str] = None) -> None:
    """登録済みボタンのアイコン名や色を変える"""
    old = _bound.get(button, ("document", "text", 18))
    bind(button, name or old[0], role or old[1], old[2])


def refresh_bound() -> None:
    for button, (name, role, size) in list(_bound.items()):
        try:
            button.setIcon(icon(name, role, size))
        except RuntimeError:
            pass  # 削除済みのウィジェット


def app_icon() -> QIcon:
    """アプリのアイコン（assets/app.ico, app.png）"""
    result = QIcon()
    for name in ("app.ico", "app-256.png"):
        path = ASSETS_DIR / name
        if path.exists():
            result.addFile(str(path))
    if result.isNull():
        svg_path = ASSETS_DIR / "app.svg"
        if svg_path.exists():
            result.addFile(str(svg_path))
    return result
