"""Excelの図形・テキストボックス・グラフ内の文字列を取り出す

openpyxl は図形（オートシェイプやテキストボックス）を読み込まないため、
xlsx（zip）内の drawing XML を直接読む。
"""

import posixpath
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"

_ANCHORS = ("twoCellAnchor", "oneCellAnchor", "absoluteAnchor")


@dataclass
class DrawingText:
    """図形内のテキスト"""
    sheet: str
    text: str
    kind: str  # shape / chart
    cell: Optional[str] = None  # 図形の左上があるセル


def _column_letter(index: int) -> str:
    """0始まりの列番号 → 列名（0 → A）"""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _read_rels(zf: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """パートのリレーション（Id → (種類, 解決済みパス)）を読む"""
    rels_path = posixpath.join(
        posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"
    )
    try:
        root = ET.fromstring(zf.read(rels_path))
    except KeyError:
        return {}
    
    rels = {}
    for rel in root.findall(f"{{{NS_PKG_REL}}}Relationship"):
        if rel.get("TargetMode") == "External":
            continue
        target = rel.get("Target", "")
        if target.startswith("/"):
            resolved = target.lstrip("/")
        else:
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(part), target))
        rels[rel.get("Id", "")] = (rel.get("Type", "").rsplit("/", 1)[-1], resolved)
    return rels


def _paragraph_text(parent: ET.Element) -> str:
    """a:p 単位で改行しながらテキストを連結"""
    lines = []
    for para in parent.iter(f"{{{NS_A}}}p"):
        line = "".join(t.text or "" for t in para.iter(f"{{{NS_A}}}t"))
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def _chart_text(zf: zipfile.ZipFile, chart_part: str) -> str:
    """グラフのタイトル・軸ラベル"""
    try:
        root = ET.fromstring(zf.read(chart_part))
    except (KeyError, ET.ParseError):
        return ""
    lines = []
    for title in root.iter(f"{{{NS_C}}}title"):
        if text := _paragraph_text(title):
            lines.append(text)
    return "\n".join(lines)


def extract_drawing_texts(xlsx_path) -> list[DrawingText]:
    """xlsx内の全シートから図形・グラフのテキストを取り出す"""
    results: list[DrawingText] = []
    
    with zipfile.ZipFile(xlsx_path) as zf:
        names = set(zf.namelist())
        if "xl/workbook.xml" not in names:
            return results
        
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        workbook_rels = _read_rels(zf, "xl/workbook.xml")
        
        for sheet in workbook.iter(f"{{{NS_MAIN}}}sheet"):
            sheet_name = sheet.get("name", "")
            _, sheet_part = workbook_rels.get(sheet.get(f"{{{NS_REL}}}id", ""), ("", ""))
            if sheet_part not in names:
                continue
            
            for rel_type, drawing_part in _read_rels(zf, sheet_part).values():
                if rel_type != "drawing" or drawing_part not in names:
                    continue
                results.extend(_read_drawing(zf, drawing_part, sheet_name))
    
    return results


def _read_drawing(zf: zipfile.ZipFile, drawing_part: str, sheet_name: str) -> list[DrawingText]:
    try:
        root = ET.fromstring(zf.read(drawing_part))
    except ET.ParseError:
        return []
    
    drawing_rels = _read_rels(zf, drawing_part)
    results = []
    
    for anchor in root:
        if anchor.tag.rsplit("}", 1)[-1] not in _ANCHORS:
            continue
        
        cell = None
        origin = anchor.find(f"{{{NS_XDR}}}from")
        if origin is not None:
            try:
                col = int(origin.findtext(f"{{{NS_XDR}}}col", "0"))
                row = int(origin.findtext(f"{{{NS_XDR}}}row", "0"))
                cell = f"{_column_letter(col)}{row + 1}"
            except ValueError:
                pass
        
        # 図形・テキストボックス（グループ内も含む）
        for shape in anchor.iter(f"{{{NS_XDR}}}sp"):
            body = shape.find(f"{{{NS_XDR}}}txBody")
            if body is not None and (text := _paragraph_text(body)):
                results.append(DrawingText(sheet_name, text, "shape", cell))
        
        # グラフ
        for chart_ref in anchor.iter(f"{{{NS_C}}}chart"):
            _, chart_part = drawing_rels.get(chart_ref.get(f"{{{NS_REL}}}id", ""), ("", ""))
            if chart_part and (text := _chart_text(zf, chart_part)):
                results.append(DrawingText(sheet_name, text, "chart", cell))
    
    return results
