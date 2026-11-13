"""配布物に同梱する第三者ライセンスを集める

使い方: uv run python tools/collect_licenses.py [出力フォルダ（既定: licenses）]

アプリが実行時に使うパッケージ（依存関係をたどったもの）について、
各パッケージに含まれる LICENSE / NOTICE などのファイルを出力フォルダへコピーし、
一覧（README.txt）を作る。
"""

import re
import shutil
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# アプリが直接使うパッケージ
ROOT_PACKAGES = [
    "PySide6-Essentials",
    "shiboken6",
    "python-pptx",
    "openpyxl",
    "python-docx",
    "pypdfium2",
    "charset-normalizer",
    "pillow",
    "cryptography",
    "pywin32",
]
LICENSE_FILE = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS|BUILD_LICENSES)", re.IGNORECASE)
# 配布物に含めない（GPL/商用ライセンスの Qt モジュールを含むが、本アプリでは使わない）パッケージの注意書き
ADDONS_NOTE = (
    "PySide6-Addons には Qt Charts など GPL/商用ライセンスのモジュールも含まれますが、"
    "本アプリはそれらを読み込まず、配布物にも含めません。"
)


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def runtime_distributions() -> list[metadata.Distribution]:
    found: dict[str, metadata.Distribution] = {}
    
    def walk(name: str) -> None:
        key = _normalize(name)
        if key in found:
            return
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            return
        found[key] = dist
        for requirement in dist.requires or []:
            if "extra ==" in requirement:
                continue
            walk(re.split(r"[ ;<>=!~\[(]", requirement, maxsplit=1)[0])
    
    for package in ROOT_PACKAGES:
        walk(package)
    return sorted(found.values(), key=lambda d: d.metadata["Name"].lower())


def license_of(dist: metadata.Distribution) -> str:
    expression = dist.metadata.get("License-Expression")
    if expression:
        return expression
    value = dist.metadata.get("License") or ""
    if value and len(value) < 100 and "\n" not in value:
        return value
    classifiers = [
        c.split("::")[-1].strip()
        for c in dist.metadata.get_all("Classifier") or []
        if c.startswith("License")
    ]
    return "; ".join(classifiers) or "（パッケージ内のライセンスファイルを参照）"


def _utf8_console() -> None:
    """日本語のメッセージを、文字コードの違うコンソールでも出せるようにする"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main() -> int:
    _utf8_console()
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "licenses"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    
    lines = [
        "Unified File Search が利用している第三者ソフトウェアのライセンス",
        "=" * 60,
        "",
    ]
    for dist in runtime_distributions():
        name = dist.metadata["Name"]
        folder = output / f"{name}-{dist.version}"
        copied = []
        for file in dist.files or []:
            path = str(file).replace("\\", "/")
            in_license_dir = "/licenses/" in path.lower()
            if not (in_license_dir or (LICENSE_FILE.search(file.name) and ".dist-info/" in path)):
                continue
            source = Path(dist.locate_file(file))
            if not source.is_file():
                continue
            # dist-info/licenses/ 以下はフォルダ構成を保ってコピーする
            relative = path.split("/licenses/", 1)[1] if in_license_dir else file.name
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append(relative)
        if _normalize(name).startswith(("pyside6", "shiboken6")):
            # Qt for Python のパッケージにはライセンス全文が含まれないため、同梱用の全文を使う
            folder.mkdir(exist_ok=True)
            for text in ("LGPL-3.0.txt", "GPL-3.0.txt"):
                shutil.copyfile(ROOT / "third_party" / text, folder / text)
                copied.append(text)
        lines.append(f"{name} {dist.version}")
        lines.append(f"  ライセンス: {license_of(dist)}")
        if copied:
            shown = ", ".join(copied[:6]) + (f" ほか {len(copied) - 6} ファイル" if len(copied) > 6 else "")
            lines.append(f"  全文: {folder.name}/ ({shown})")
        if _normalize(name) == "pyside6-addons":
            lines.append(f"  注意: {ADDONS_NOTE}")
        lines.append("")
    
    lines += [
        "Qt for Python（PySide6）は LGPL-3.0 で提供されています。",
        "Qt のソースコードは https://download.qt.io/ から入手できます。",
        "Qt のライブラリ（DLL）は差し替え可能な形で同梱しています。",
    ]
    (output / "README.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"{output} に {len(runtime_distributions())} パッケージ分のライセンスを集めました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
