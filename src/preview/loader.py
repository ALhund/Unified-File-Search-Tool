"""プレビューの組み立て

ファイルの種類と環境に応じて表示方法を選ぶ:

- PDF                … そのままページ表示
- Word/Excel/PowerPoint … PDFへ変換してページ表示（変換できなければテキスト表示）
- テキスト           … 行番号付きのテキスト表示
"""

from pathlib import Path
from typing import Optional

from src.common.logger import get_logger
from src.common.config import get_config
from src.enumeration import FileInfo
from src.metadata import MetadataReader
from src.preview.converter import OFFICE_EXTENSIONS, available_backends, convert_to_pdf
from src.preview.page_document import PageDocument
from src.preview.preview_renderer import PreviewRenderer, RenderedPreview
from src.search.query import CompiledQuery, QueryError, SearchOptions
from src.search.searcher import load_content

BACKEND_NAMES = {"msoffice": "Microsoft Office", "libreoffice": "LibreOffice"}


def supports_page_mode(extension: str) -> bool:
    """原本表示（ページ表示）が可能な種類か"""
    if extension == "pdf":
        return True
    return extension in OFFICE_EXTENSIONS and bool(available_backends(extension))


def build_preview(
    file_info: FileInfo,
    options: Optional[SearchOptions],
    mode: str = "auto",
) -> RenderedPreview:
    """プレビューを生成する（時間がかかるのでUIスレッド以外で呼ぶ）
    
    Args:
        file_info: 対象ファイル
        options: 検索条件（マッチ箇所の強調に使う。None なら強調なし）
        mode: "auto"（可能なら原本表示）/ "text"（テキスト表示）
    """
    logger = get_logger("preview")
    renderer = PreviewRenderer()
    config = get_config()
    
    query: Optional[CompiledQuery] = None
    if options is not None:
        try:
            query = CompiledQuery(options)
        except QueryError:
            query = None
    
    extension = file_info.extension
    preview = RenderedPreview()
    preview.info = _file_info_text(file_info)
    preview.page_mode_available = supports_page_mode(extension)
    
    if mode != "text" and (extension == "pdf" or extension in OFFICE_EXTENSIONS):
        pdf_path: Optional[Path] = None
        if extension == "pdf":
            pdf_path = file_info.path
        else:
            conversion = convert_to_pdf(file_info.path)
            if conversion.pdf_path:
                pdf_path = conversion.pdf_path
            else:
                preview.note = (
                    "原本表示に切り替えられないため、テキスト表示にしています"
                    f"（{conversion.error}）"
                )
        
        if pdf_path is not None:
            try:
                document = PageDocument(
                    pdf_path, fit_to_content=extension in ("xlsx", "xlsm", "xls")
                )
                _apply_labels(file_info, document)
                hits, truncated = (
                    document.find_hits(query, config.preview_max_hits) if query else ([], False)
                )
                preview.page_hits = hits
                preview.hits = renderer.page_hit_labels(document, hits)
                preview.mode = "page"
                preview.sections = list(document.labels)
                preview.page_document = document
                preview.truncated = truncated
                return preview
            except Exception as e:
                logger.exception("page_view", f"Failed to build page view: {file_info.path}", e)
                preview.note = f"ページ表示を生成できなかったため、テキスト表示にしています（{e}）"
    
    content = load_content(file_info)
    if content.error:
        preview.note = _join_notes(preview.note, f"読み込みエラー: {content.error}")
    if content.total_lines is not None:
        # テキストファイル: 行番号つきでそのまま
        preview.plain_text, preview.plain_hits, preview.hits, preview.truncated = renderer.render_plain(
            content, query, config.preview_max_hits
        )
        preview.encoding = content.encoding or ""
        preview.mode = "plain"
        return preview
    
    preview.html, preview.hits, preview.truncated = renderer.render_text(
        content, query, config.preview_max_hits
    )
    preview.mode = "rich"
    preview.sections = renderer.last_sections
    return preview


def _join_notes(*notes: str) -> str:
    return " / ".join(n for n in notes if n)


def _file_info_text(file_info: FileInfo) -> str:
    """作成者などのファイル情報（取得できたものだけ）"""
    try:
        metadata = MetadataReader().read(file_info.path)
    except Exception:
        return ""
    parts = []
    if metadata.author:
        parts.append(f"作成者: {metadata.author}")
    if metadata.last_modified_by:
        parts.append(f"最終更新者: {metadata.last_modified_by}")
    if metadata.created:
        parts.append(f"作成日: {metadata.created:%Y/%m/%d %H:%M}")
    parts.append(f"更新日: {file_info.modified_time:%Y/%m/%d %H:%M}")
    return "  |  ".join(parts)


def _visible_sheets(path: Path) -> list[str]:
    """表示されているシートの名前（非表示のシートは PDF に出力されない）"""
    if path.suffix.lower() == ".xls":
        import xlrd
        book = xlrd.open_workbook(str(path), on_demand=True)
        try:
            return [book.sheet_by_index(i).name for i in range(book.nsheets)
                    if book.sheet_by_index(i).visibility == 0]
        finally:
            book.release_resources()
    from openpyxl import load_workbook
    workbook = load_workbook(str(path), read_only=True)
    try:
        return [ws.title for ws in workbook.worksheets if ws.sheet_state == "visible"]
    finally:
        workbook.close()


def _apply_labels(file_info: FileInfo, document: PageDocument) -> None:
    """変換後のページに「シート名」「スライド番号」を対応付ける
    
    対応が確実に取れたときだけ付ける（それ以外は「ページ N」のまま）。
    """
    extension = file_info.extension
    count = document.page_count
    try:
        if extension in ("pptx", "ppt"):
            if load_content(file_info).total_slides == count:
                document.labels = [f"スライド {i + 1}" for i in range(count)]
            return
        if extension not in ("xlsx", "xlsm", "xls"):
            return
        
        visible = _visible_sheets(file_info.path)
        
        # シートは複数ページにまたがることがあるので、各シートの先頭ページを求める
        starts = document.sheet_start_pages()
        if not starts or starts[0] != 0:
            return
        if len(starts) != len(visible):
            # 空のシートはPDFに出力されないので、内容のあるシートだけで数え直す
            used = {block.sheet for block in load_content(file_info).blocks}
            visible = [name for name in visible if name in used]
            if len(starts) != len(visible):
                return
        
        labels = []
        for i, name in enumerate(visible):
            end = starts[i + 1] if i + 1 < len(starts) else count
            pages = end - starts[i]
            for n in range(pages):
                suffix = f"（{n + 1}/{pages}）" if pages > 1 else ""
                labels.append(f"シート: {name}{suffix}")
        document.labels = labels
    except Exception:
        pass
