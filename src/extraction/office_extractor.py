"""Office 形式テキスト抽出モジュール（.docx / .xlsx / .pptx）。

各クラスは python-docx / openpyxl / python-pptx を遅延インポートして
対応形式のテキストを :class:`ContentBlock` 単位で抽出する。
"""

from pathlib import Path

from src.common.logger import get_logger
from src.extraction.base import ContentBlock, ExtractedContent, TextExtractor


class WordExtractor(TextExtractor):
    """Word（.docx）からテキストを抽出する Extractor。

    段落と表セルを順に走査し、見出しスタイルを
    :attr:`ContentBlock.heading_level` に反映する。
    """

    def __init__(self) -> None:
        self._logger = get_logger("extraction")

    @property
    def supported_extensions(self) -> set[str]:
        """サポートする拡張子: ``{"docx"}``。"""
        return {"docx"}

    def extract(self, file_path: Path) -> ExtractedContent:
        """Word ファイルからコンテンツを抽出する。

        ``doc.element.body`` を走査して段落と表を文書順に取得する。
        見出しスタイル（Heading 1–6）は ``heading_level`` に、
        リストスタイル（List Bullet / List Number 等）は ``list_level`` / ``list_is_ordered`` に反映する。

        Args:
            file_path: 抽出対象の .docx ファイルパス。

        Returns:
            抽出されたコンテンツ。エラー時は ``error`` が設定される。
        """
        from docx import Document
        from docx.opc.exceptions import PackageNotFoundError
        from docx.oxml.ns import qn
        from docx.text.paragraph import Paragraph
        from docx.table import Table

        result = ExtractedContent(file_path=file_path)

        try:
            doc = Document(file_path)
            item_num = 0

            # doc.element.body の直接の子要素を順番に走査することで
            # 段落と表が文書中に現れる順序を正確に保持する
            for child in doc.element.body:
                tag = child.tag

                if tag == qn("w:p"):
                    para = Paragraph(child, doc)
                    text = para.text.strip()
                    if not text:
                        continue
                    item_num += 1
                    heading_level = _parse_heading_level(para.style.name)
                    list_level, list_is_ordered = _parse_list_info(para.style.name)
                    result.blocks.append(ContentBlock(
                        text=text,
                        page=1,
                        line=item_num,
                        heading_level=heading_level,
                        list_level=list_level,
                        list_is_ordered=list_is_ordered,
                    ))

                elif tag == qn("w:tbl"):
                    table = Table(child, doc)
                    # 結合セルの重複テキストを避けるため、走査済み座標を追跡する
                    seen_coords: set[tuple[int, int]] = set()
                    for ri, row in enumerate(table.rows):
                        for ci, cell in enumerate(row.cells):
                            if (ri, ci) in seen_coords:
                                continue
                            seen_coords.add((ri, ci))
                            text = cell.text.strip()
                            if text:
                                item_num += 1
                                result.blocks.append(ContentBlock(
                                    text=text,
                                    page=1,
                                    line=item_num,
                                ))

            result.total_pages = 1

            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from Word file",
                file_path=str(file_path),
            )

        except PackageNotFoundError:
            result.error = (
                "ファイルが破損しているか、有効な docx ファイルではありません"
            )
            self._logger.warning(
                "skip",
                f"Invalid docx file: {file_path}",
                file_path=str(file_path),
            )

        except Exception as exc:
            result.error = str(exc)
            self._logger.exception(
                "error",
                f"Failed to extract from Word: {file_path}",
                exc,
                file_path=str(file_path),
            )

        return result


class ExcelExtractor(TextExtractor):
    """Excel（.xlsx）からテキストを抽出する Extractor。

    全シートのセル値を走査し、シート名とセル座標を
    :class:`ContentBlock` に記録する。
    """

    def __init__(self) -> None:
        self._logger = get_logger("extraction")

    @property
    def supported_extensions(self) -> set[str]:
        """サポートする拡張子: ``{"xlsx"}``。"""
        return {"xlsx"}

    def extract(self, file_path: Path) -> ExtractedContent:
        """Excel ファイルからコンテンツを抽出する。

        read_only・data_only モードでワークブックを開き、
        全シートの全セルを走査する。空セルはスキップする。

        Args:
            file_path: 抽出対象の .xlsx ファイルパス。

        Returns:
            抽出されたコンテンツ。エラー時は ``error`` が設定される。
        """
        from openpyxl import load_workbook
        from openpyxl.utils.exceptions import InvalidFileException

        result = ExtractedContent(file_path=file_path)

        try:
            wb = load_workbook(file_path, read_only=True, data_only=True)
            result.total_sheets = len(wb.sheetnames)

            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                for row in sheet.iter_rows():
                    for cell in row:
                        if cell.value is None:
                            continue
                        text = str(cell.value).strip()
                        if text:
                            result.blocks.append(ContentBlock(
                                text=text,
                                sheet=sheet_name,
                                cell=cell.coordinate,
                            ))

            wb.close()

            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from Excel file",
                file_path=str(file_path),
                sheets=result.total_sheets,
            )

        except InvalidFileException:
            result.error = (
                "ファイルが破損しているか、有効な xlsx ファイルではありません"
            )
            self._logger.warning(
                "skip",
                f"Invalid xlsx file: {file_path}",
                file_path=str(file_path),
            )

        except Exception as exc:
            result.error = str(exc)
            self._logger.exception(
                "error",
                f"Failed to extract from Excel: {file_path}",
                exc,
                file_path=str(file_path),
            )

        return result


class PowerPointExtractor(TextExtractor):
    """PowerPoint（.pptx）からテキストを抽出する Extractor。

    全スライドのシェイプ・表を走査し、タイトルプレースホルダーを
    :attr:`ContentBlock.is_slide_title` で識別する。
    """

    def __init__(self) -> None:
        self._logger = get_logger("extraction")

    @property
    def supported_extensions(self) -> set[str]:
        """サポートする拡張子: ``{"pptx"}``。"""
        return {"pptx"}

    def extract(self, file_path: Path) -> ExtractedContent:
        """PowerPoint ファイルからコンテンツを抽出する。

        各スライドのシェイプテキストと表セルテキストを走査する。
        タイトルプレースホルダー（idx == 0）は ``is_slide_title=True`` で記録する。

        Args:
            file_path: 抽出対象の .pptx ファイルパス。

        Returns:
            抽出されたコンテンツ。エラー時は ``error`` が設定される。
        """
        from pptx import Presentation
        from pptx.exc import PackageNotFoundError

        result = ExtractedContent(file_path=file_path)

        try:
            prs = Presentation(file_path)
            result.total_slides = len(prs.slides)

            for slide_num, slide in enumerate(prs.slides, start=1):
                for shape in slide.shapes:
                    is_title = _is_title_placeholder(shape)

                    if hasattr(shape, "text"):
                        text = shape.text.strip()
                        if text:
                            result.blocks.append(ContentBlock(
                                text=text,
                                slide=slide_num,
                                is_slide_title=is_title,
                            ))

                    # 表内のテキスト（タイトル以外のシェイプも対象）
                    if shape.has_table:
                        for row in shape.table.rows:
                            for cell in row.cells:
                                text = cell.text.strip()
                                if text:
                                    result.blocks.append(ContentBlock(
                                        text=text,
                                        slide=slide_num,
                                    ))

            self._logger.debug(
                "extract",
                f"Extracted {len(result.blocks)} blocks from PowerPoint file",
                file_path=str(file_path),
                slides=result.total_slides,
            )

        except PackageNotFoundError:
            result.error = (
                "ファイルが破損しているか、有効な pptx ファイルではありません"
            )
            self._logger.warning(
                "skip",
                f"Invalid pptx file: {file_path}",
                file_path=str(file_path),
            )

        except Exception as exc:
            result.error = str(exc)
            self._logger.exception(
                "error",
                f"Failed to extract from PowerPoint: {file_path}",
                exc,
                file_path=str(file_path),
            )

        return result


# ---------------------------------------------------------------------------
# ヘルパー関数（モジュール内共有）
# ---------------------------------------------------------------------------

def _parse_heading_level(style_name: str) -> int | None:
    """Word 段落スタイル名から見出しレベルを取得する。

    スタイル名が ``"Heading 1"`` や ``"見出し 3"`` の形式の場合に
    数値（1–6）を返す。それ以外は ``None`` を返す。

    Args:
        style_name: Word 段落スタイルの名前（例: ``"Heading 2"``）。

    Returns:
        見出しレベル（1–6）、または見出しスタイルでない場合は ``None``。
    """
    if not style_name:
        return None
    parts = style_name.split()
    if len(parts) == 2 and parts[0].lower() in ("heading", "見出し"):
        try:
            level = int(parts[1])
            return level if 1 <= level <= 6 else None
        except ValueError:
            return None
    return None


def _parse_list_info(style_name: str) -> tuple[int | None, bool]:
    """Word 段落スタイル名からリスト情報を取得する。

    スタイル名が ``"List Bullet"`` / ``"List Number"`` 等の場合に
    (インデントレベル, 順序付きか) を返す。それ以外は ``(None, False)`` を返す。

    Args:
        style_name: Word 段落スタイルの名前（例: ``"List Bullet 2"``）。

    Returns:
        ``(list_level, list_is_ordered)`` のタプル。リスト以外は ``(None, False)``。
    """
    if not style_name:
        return (None, False)

    name_lower = style_name.lower()

    # 英語スタイル: "List Bullet", "List Bullet 2" など
    bullet_styles = ("list bullet", "list paragraph", "bullet list",
                     "箇条書き", "リスト段落")
    number_styles = ("list number", "list continue", "number list",
                     "番号付き", "リスト番号")

    for prefix in bullet_styles:
        if name_lower.startswith(prefix):
            # スタイル名末尾の数字がインデントレベルを表す（例: "List Bullet 2" → level 1）
            suffix = name_lower[len(prefix):].strip()
            try:
                level = max(0, int(suffix) - 1)
            except ValueError:
                level = 0
            return (level, False)

    for prefix in number_styles:
        if name_lower.startswith(prefix):
            suffix = name_lower[len(prefix):].strip()
            try:
                level = max(0, int(suffix) - 1)
            except ValueError:
                level = 0
            return (level, True)

    return (None, False)


def _is_title_placeholder(shape: object) -> bool:
    """Shape がタイトル系プレースホルダーかどうかを判定する。

    タイトルプレースホルダーは ``placeholder_format.idx == 0`` で識別する
    （idx=0 はタイトル・センタータイトル共通）。

    Args:
        shape: python-pptx の Shape オブジェクト。

    Returns:
        タイトル系プレースホルダーであれば ``True``。
    """
    try:
        if shape.is_placeholder:  # type: ignore[union-attr]
            return shape.placeholder_format.idx == 0  # type: ignore[union-attr]
    except Exception:
        pass
    return False
