"""実行ファイル（配布用フォルダと zip）を作る

使い方（リポジトリのフォルダで）:
    python packaging/build.py

出力:
    dist/UnifiedFileSearch/                 … 実行ファイルと同梱物（このフォルダごと配布）
    dist/UnifiedFileSearch-<版>-<OS>.zip     … 上のフォルダの zip

PyInstaller はそのOS用の実行ファイルしか作れない。Windows 用は Windows で実行すること
（GitHub Actions の .github/workflows/build-windows.yml が自動で行う）。
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import APP_NAME, __version__  # noqa: E402

DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP_FOLDER = DIST / "UnifiedFileSearch"


def version_file() -> Path:
    """Windows のファイルのプロパティに出す情報"""
    parts = [int(p) for p in __version__.split(".")[:3]] + [0]
    numbers = tuple((parts + [0, 0, 0, 0])[:4])
    text = f"""
VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041104B0', [
      StringStruct('CompanyName', '{APP_NAME}'),
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'UnifiedFileSearch'),
      StringStruct('LegalCopyright', '© {APP_NAME}'),
      StringStruct('OriginalFilename', 'UnifiedFileSearch.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [0x0411, 1200])])
  ]
)
"""
    BUILD.mkdir(exist_ok=True)
    path = BUILD / "version_info.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _utf8_console() -> None:
    """日本語のメッセージを、文字コードの違うコンソールでも出せるようにする"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main() -> int:
    _utf8_console()
    shutil.rmtree(APP_FOLDER, ignore_errors=True)
    
    env = dict(**__import__("os").environ)
    if sys.platform == "win32":
        env["UFST_VERSION_FILE"] = str(version_file())
    
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"),
         str(ROOT / "packaging" / "UnifiedFileSearch.spec")],
        check=True,
        cwd=ROOT,
        env=env,
    )
    
    # 利用者が見る・編集するファイルは実行ファイルの隣に置く
    shutil.copytree(ROOT / "Config", APP_FOLDER / "Config")
    shutil.copyfile(ROOT / "THIRD_PARTY_NOTICES.md", APP_FOLDER / "THIRD_PARTY_NOTICES.md")
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "collect_licenses.py"), str(APP_FOLDER / "licenses")],
        check=True,
    )
    
    system = {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), platform.system().lower())
    archive = shutil.make_archive(str(DIST / f"UnifiedFileSearch-{__version__}-{system}"), "zip", DIST, "UnifiedFileSearch")
    size = sum(f.lstat().st_size for f in APP_FOLDER.rglob("*") if f.is_file() and not f.is_symlink())
    print(f"作成しました: {APP_FOLDER}（{size / 1024 / 1024:.0f} MB）")
    print(f"作成しました: {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
