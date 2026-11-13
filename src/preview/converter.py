"""Officeファイル → PDF 変換

「直接開いたのと同じ見た目」を得るため、Officeファイルを一度PDFへ変換してから
ページ画像として表示する。図形・グラフ・画像・罫線・書式がそのまま再現される。

変換エンジン（設定 office_converter で選択、auto は上から順に試す）:
  1. msoffice    … Windows上のMicrosoft Office（COM経由）。最も忠実。
  2. libreoffice … LibreOffice（soffice）。OSを問わず利用可能。

どちらも使えない場合は None を返し、呼び出し側がテキスト表示に切り替える。
"""

import hashlib
from functools import lru_cache
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.common.config import get_config
from src.common.logger import get_logger

OFFICE_EXTENSIONS = {"docx", "xlsx", "xlsm", "pptx", "xls", "doc", "ppt"}
SPREADSHEET_EXTENSIONS = {"xlsx", "xlsm", "xls"}

# 同時に複数の変換を走らせない（LibreOfficeのプロファイル競合を避ける）
_convert_lock = threading.Lock()


@dataclass
class ConversionResult:
    pdf_path: Optional[Path] = None
    backend: str = ""  # msoffice / libreoffice / cache
    error: str = ""


def find_libreoffice() -> Optional[str]:
    """LibreOffice（soffice）の実行ファイルを探す"""
    configured = get_config().libreoffice_path
    if configured:
        return configured if Path(configured).exists() else None
    
    for name in ("soffice", "libreoffice"):
        if found := shutil.which(name):
            return found
    
    candidates = []
    if sys.platform == "win32":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            if base := os.environ.get(env):
                candidates.append(Path(base) / "LibreOffice" / "program" / "soffice.exe")
                candidates.append(Path(base) / "Programs" / "LibreOffice" / "program" / "soffice.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    else:
        candidates += [Path("/usr/lib/libreoffice/program/soffice"), Path("/opt/libreoffice/program/soffice")]
    
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


# 拡張子 → Microsoft Office のアプリ（COM の ProgID）
OFFICE_PROGIDS = {
    "xlsx": "Excel.Application",
    "xls": "Excel.Application",
    "doc": "Word.Application",
    "ppt": "PowerPoint.Application",
    "xlsm": "Excel.Application",
    "docx": "Word.Application",
    "pptx": "PowerPoint.Application",
}


@lru_cache(maxsize=8)
def _progid_registered(progid: str) -> bool:
    """そのOfficeアプリがインストールされているか（COM の登録をレジストリで確認）"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{progid}\CLSID"):
            return True
    except OSError:
        return False


def has_msoffice_support(extension: Optional[str] = None) -> bool:
    """Microsoft Office で変換できるか
    
    pywin32 があり、該当する Office アプリ（拡張子を省略した場合はいずれか）が
    インストールされているときだけ True。
    """
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    if extension is not None:
        progid = OFFICE_PROGIDS.get(extension.lower().lstrip("."))
        return progid is not None and _progid_registered(progid)
    return any(_progid_registered(p) for p in set(OFFICE_PROGIDS.values()))


def available_backends(extension: Optional[str] = None) -> list[str]:
    """利用可能な変換エンジンを優先順に返す（拡張子を渡すとその種類で使えるものだけ）"""
    setting = get_config().office_converter
    if setting == "none":
        return []
    
    backends = []
    if setting in ("auto", "msoffice") and has_msoffice_support(extension):
        backends.append("msoffice")
    if setting in ("auto", "libreoffice") and find_libreoffice():
        backends.append("libreoffice")
    return backends


def _cache_dir() -> Path:
    path = get_config().cache_path / "preview"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(src: Path) -> str:
    stat = src.stat()
    raw = f"{src.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
    return hashlib.sha1(raw.encode("utf-8", "surrogatepass")).hexdigest()


def convert_to_pdf(src: Path) -> ConversionResult:
    """OfficeファイルをPDFに変換する（変換結果はキャッシュする）"""
    logger = get_logger("preview")
    src = Path(src)
    
    try:
        cached = _cache_dir() / f"{_cache_key(src)}.pdf"
    except OSError as e:
        return ConversionResult(error=str(e))
    
    if cached.exists() and cached.stat().st_size > 0:
        os.utime(cached)  # 最近使ったものとして扱う
        return ConversionResult(pdf_path=cached, backend="cache")
    
    backends = available_backends(src.suffix)
    if not backends:
        return ConversionResult(error="変換エンジン（Microsoft Office / LibreOffice）が見つかりません")
    
    timeout = get_config().preview_conversion_timeout_sec
    errors = []
    
    with _convert_lock:
        for backend in backends:
            with tempfile.TemporaryDirectory(prefix="ufst_conv_") as tmp:
                work = Path(tmp)
                # 元ファイルには触れず、作業用コピーを変換する
                # （ロックファイルを作らない・日本語パスでの不具合を避ける）
                work_src = work / f"source{src.suffix.lower()}"
                out_pdf = work / "source.pdf"
                try:
                    _prepare_working_copy(src, work_src)
                    if backend == "msoffice":
                        _convert_with_msoffice(work_src, out_pdf, timeout)
                    else:
                        if work_src.suffix.lower() == ".xls":
                            # 旧形式の Excel は一度 .xlsx にしてから、枠線・行列番号の設定を入れる
                            work_src = _xls_to_patched_xlsx(work_src, work, timeout)
                        _convert_with_libreoffice(work_src, work, timeout)
                    
                    if out_pdf.exists() and out_pdf.stat().st_size > 0:
                        shutil.move(str(out_pdf), str(cached))
                        logger.info("convert", f"Converted with {backend}", file_path=str(src))
                        return ConversionResult(pdf_path=cached, backend=backend)
                    errors.append(f"{backend}: PDFが生成されませんでした")
                
                except subprocess.TimeoutExpired:
                    errors.append(f"{backend}: 変換が{timeout}秒以内に終わりませんでした")
                except Exception as e:
                    errors.append(f"{backend}: {e}")
    
    message = " / ".join(errors)
    logger.warning("convert", f"Conversion failed: {message}", file_path=str(src))
    return ConversionResult(error=message)


def _prepare_working_copy(src: Path, work_src: Path) -> None:
    """変換用の作業コピーを作る
    
    Excelは画面で開いたときと同じように、枠線（グリッド）と行列番号を付け、
    全ての列が1ページの幅に収まるよう印刷設定を書き換えたコピーを変換する（元ファイルは変更しない）。
    """
    if work_src.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            _copy_xlsx_with_gridlines(src, work_src)
            return
        except Exception as e:
            get_logger("preview").warning(
                "convert", "Failed to patch print options", file_path=str(src), exception_message=str(e)
            )
    shutil.copyfile(src, work_src)


# printOptions より後ろに来る要素（スキーマ上の並び順を守って挿入するために使う）
_AFTER_PRINT_OPTIONS = (
    "headerFooter", "rowBreaks", "colBreaks", "customProperties",
    "cellWatches", "ignoredErrors", "smartTags", "drawing", "legacyDrawing", "legacyDrawingHF",
    "drawingHF", "picture", "oleObjects", "controls", "webPublishItems", "tableParts", "extLst",
)
_INSERT_POINT_RE = re.compile(
    r"<(?:" + "|".join(_AFTER_PRINT_OPTIONS) + r")\b|</worksheet>"
)
_SHEET_VIEW_RE = re.compile(r"<sheetView\b[^>]*>")
_WORKSHEET_OPEN_RE = re.compile(r"<worksheet\b[^>]*>")
_SHEET_PR_EMPTY_RE = re.compile(r"<sheetPr\b([^>]*)/>")
_SHEET_PR_CLOSE = "</sheetPr>"
_PRINT_AREA_RE = re.compile(
    r'<definedName\b[^>]*\bname="_xlnm\.Print_(?:Area|Titles)"[^>]*>.*?</definedName>', re.DOTALL
)
_FIT_TO_PAGE = '<pageSetUpPr fitToPage="1"/>'
# 用紙はA3横（paperSize=8）。横幅が1ページに収まるよう縮小され（縦は必要なだけページを使う）、
# 表示時に元の大きさへ戻す
_PAGE_SETTINGS = (
    '<pageMargins left="0.2" right="0.2" top="0.2" bottom="0.2" header="0" footer="0"/>'
    '<pageSetup paperSize="8" orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
)


def _remove_elements(xml: str, *names: str) -> str:
    """指定した要素（自己終了・開始〜終了のどちらの形でも）を取り除く"""
    for name in names:
        xml = re.sub(rf"<{name}\b[^>]*?/>", "", xml)
        xml = re.sub(rf"<{name}\b[^>]*>.*?</{name}>", "", xml, flags=re.DOTALL)
    return xml


def patch_sheet_xml(xml: str) -> str:
    """シートXMLの印刷設定を「画面で開いたときの見た目」に書き換える
    
    - 枠線（グリッド）と行列番号を出力する
    - 印刷範囲・改ページ・印刷用ヘッダー/フッターを無効にし、全ての列を1ページの幅に収める
    """
    opening = _WORKSHEET_OPEN_RE.search(xml)
    if opening is None:
        return xml  # グラフシート等
    
    def view_flag(name: str) -> bool:
        view = _SHEET_VIEW_RE.search(xml)
        return not (view and re.search(rf'\b{name}="(?:0|false)"', view.group(0)))
    
    # 利用者が枠線・見出しを非表示にしているシートはそれに従う
    options = (
        f'<printOptions gridLines="{int(view_flag("showGridLines"))}" '
        f'headings="{int(view_flag("showRowColHeaders"))}"/>'
    )
    xml = _remove_elements(
        xml, "printOptions", "pageMargins", "pageSetup", "headerFooter",
        "rowBreaks", "colBreaks", "pageSetUpPr",
    )
    
    # sheetPr に「ページに収める」を設定する
    if _SHEET_PR_EMPTY_RE.search(xml):
        xml = _SHEET_PR_EMPTY_RE.sub(rf"<sheetPr\1>{_FIT_TO_PAGE}</sheetPr>", xml, count=1)
    elif _SHEET_PR_CLOSE in xml:
        xml = xml.replace(_SHEET_PR_CLOSE, _FIT_TO_PAGE + _SHEET_PR_CLOSE, 1)
    else:
        end = _WORKSHEET_OPEN_RE.search(xml).end()
        xml = xml[:end] + f"<sheetPr>{_FIT_TO_PAGE}</sheetPr>" + xml[end:]
    
    point = _INSERT_POINT_RE.search(xml)
    if point is None:
        return xml
    return xml[:point.start()] + options + _PAGE_SETTINGS + xml[point.start():]


def _copy_xlsx_with_gridlines(src: Path, dst: Path) -> None:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            name = item.filename
            if name.startswith("xl/worksheets/") and name.endswith(".xml") and "/_rels/" not in name:
                data = patch_sheet_xml(data.decode("utf-8")).encode("utf-8")
            elif name == "xl/workbook.xml":
                data = _PRINT_AREA_RE.sub("", data.decode("utf-8")).encode("utf-8")
            zout.writestr(item, data)


def _hidden_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _xls_to_patched_xlsx(work_src: Path, work: Path, timeout: int) -> Path:
    staging = work / "xlsx"
    staging.mkdir(exist_ok=True)
    _convert_with_libreoffice(work_src, staging, timeout, target="xlsx")
    converted = staging / (work_src.stem + ".xlsx")
    if not converted.exists():
        return work_src
    patched = work / (work_src.stem + ".xlsx")
    try:
        _copy_xlsx_with_gridlines(converted, patched)
    except Exception:
        shutil.copyfile(converted, patched)
    return patched


def _convert_with_libreoffice(work_src: Path, out_dir: Path, timeout: int, target: str = "pdf") -> None:
    soffice = find_libreoffice()
    if not soffice:
        raise RuntimeError("LibreOfficeが見つかりません")
    
    # 専用プロファイルを使い、ユーザーが開いているLibreOfficeと干渉させない
    profile = get_config().cache_path / "lo_profile"
    profile.mkdir(parents=True, exist_ok=True)
    
    command = [
        soffice,
        "--headless",
        "--norestore",
        "--nolockcheck",
        f"-env:UserInstallation={profile.resolve().as_uri()}",
        "--convert-to",
        target,
        "--outdir",
        str(out_dir),
        str(work_src),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        timeout=timeout,
        creationflags=_hidden_window_flags(),
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()[-300:]
        raise RuntimeError(f"終了コード {completed.returncode} {detail}")


def _convert_with_msoffice(work_src: Path, out_pdf: Path, timeout: int) -> None:
    # COMは別プロセスで実行する（タイムアウトで確実に止められ、UIスレッドのCOM状態に影響しない）
    from src.common.paths import app_dir, is_frozen
    
    if is_frozen():
        # 実行ファイルでは自分自身を変換モードで起動する（main.py が受け付ける）
        command = [sys.executable, "--convert-with-msoffice", str(work_src), str(out_pdf)]
    else:
        command = [sys.executable, "-m", "src.preview.msoffice_convert", str(work_src), str(out_pdf)]
    completed = subprocess.run(
        command,
        cwd=str(app_dir()),
        capture_output=True,
        timeout=timeout,
        creationflags=_hidden_window_flags(),
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()[-300:]
        raise RuntimeError(detail or f"終了コード {completed.returncode}")


def prune_preview_cache(max_bytes: Optional[int] = None) -> None:
    """変換済みPDFのキャッシュが上限を超えていたら古いものから削除する"""
    if max_bytes is None:
        max_bytes = get_config().cache_max_size_mb * 1024 * 1024
    try:
        files = sorted(_cache_dir().glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        total = 0
        for path in files:
            total += path.stat().st_size
            if total > max_bytes:
                path.unlink(missing_ok=True)
    except OSError:
        pass
