# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller の設定（packaging/build.py から使う）

- フォルダ形式（onedir）で作る。Qt（LGPL）の DLL を差し替え可能な形で同梱するため、
  1ファイル形式（onefile）にはしない
- GPL/商用ライセンスの Qt モジュール（Qt Charts など）や使わないモジュールは含めない
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
APP_NAME = "UnifiedFileSearch"

# 使わない・ライセンス上含めたくない Qt モジュール
QT_EXCLUDES = [
    "QtCharts", "QtDataVisualization", "QtGraphs", "QtGraphsWidgets",  # GPL/商用
    "Qt3DAnimation", "Qt3DCore", "Qt3DExtras", "Qt3DInput", "Qt3DLogic", "Qt3DRender",
    "QtQuick3D", "QtMultimedia", "QtMultimediaWidgets", "QtSpatialAudio", "QtTextToSpeech",
    "QtBluetooth", "QtNfc", "QtSensors", "QtSerialBus", "QtSerialPort", "QtRemoteObjects",
    "QtScxml", "QtStateMachine", "QtHttpServer", "QtNetworkAuth", "QtWebSockets", "QtWebView",
    "QtCanvasPainter", "QtDesigner", "QtUiTools", "QtHelp", "QtSql", "QtTest", "QtQuickTest",
    "QtPdf", "QtPdfWidgets", "QtLocation", "QtWebEngineQuick", "QtQuickControls2",
    "QtQuickWidgets", "QtOpenGLWidgets", "QtLabsStyleKit", "QtConcurrent", "QtDBus",
]

datas = [
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
datas += collect_data_files("pypdfium2_raw")
datas += collect_data_files("pypdfium2")
binaries = collect_dynamic_libs("pypdfium2_raw")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "src.preview.msoffice_convert",
        "src.selftest",
        "charset_normalizer.md__mypyc",
    ],
    excludes=[f"PySide6.{name}" for name in QT_EXCLUDES]
    + ["tkinter", "pytest", "PyInstaller", "IPython", "numpy", "matplotlib"],
    noarchive=False,
)
# ---------------------------------------------------------------------------
# 同梱する Qt を必要なものだけに絞る（許可リスト方式）
#   PySide6 のフックは QML 関連で多くのモジュールを集めるが、その中には
#   GPL/商用ライセンスのもの（Qt Charts, Qt Virtual Keyboard など）も含まれる。
# ---------------------------------------------------------------------------
import re

QT_ALLOWED = {
    # 画面
    "Core", "Gui", "Widgets", "Svg", "SvgWidgets", "PrintSupport", "OpenGL", "Network", "DBus",
    # Qt WebEngine（プレビュー）とその依存
    "WebEngineCore", "WebEngineWidgets", "WebChannel", "Positioning",
    "Qml", "QmlMeta", "QmlModels", "QmlWorkerScript", "Quick", "QuickWidgets",
    # Linux 用の表示プラグインの依存（Windows には存在しない）
    "XcbQpa", "WaylandClient", "WlShellIntegration", "EglFSDeviceIntegration", "EglFsKmsSupport",
}
QT_LIB = re.compile(r"(?:^|[/\\])(?:lib)?Qt6([A-Za-z0-9]+?)(?:d)?\.(?:dll|so[.\d]*|dylib)$")
# 使わないプラグインの種類
PLUGIN_BLOCK = (
    "sqldrivers", "multimedia", "qmltooling", "sceneparsers", "geometryloaders", "renderers",
    "renderplugins", "sensors", "texttospeech", "virtualkeyboard", "position", "canbus",
    "assetimporters", "designer", "help", "webview", "generic", "networkinformation",
    "qmllint", "qmlls", "scxmldatamodel",
)


def _keep(dest: str) -> bool:
    path = dest.replace("\\", "/")
    if "/Qt/qml/" in path or path.startswith("PySide6/qml/"):
        return False  # QML は使わない
    if "/translations/" in path:
        # WebEngine の言語データと Qt の翻訳は日本語・英語だけ残す
        name = path.rsplit("/", 1)[-1]
        return name in ("ja.pak", "en-US.pak") or name.endswith("_ja.qm")
    if "/plugins/" in path:
        kind = path.split("/plugins/", 1)[1].split("/", 1)[0]
        if kind in PLUGIN_BLOCK:
            return False
    match = QT_LIB.search(path)
    if match and "PySide6" in path and match.group(1) not in QT_ALLOWED:
        return False
    return True


a.binaries = [entry for entry in a.binaries if _keep(entry[0])]
a.datas = [entry for entry in a.datas if _keep(entry[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    icon=str(ROOT / "assets" / "app.ico"),
    version=os.environ.get("UFST_VERSION_FILE") or None,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name=APP_NAME,
    upx=False,
)
