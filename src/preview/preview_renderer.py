"""プレビューレンダラーモジュール

ファイル内容をHTMLでレンダリングし、マッチ箇所を強調表示する。
"""

import html
import re
from pathlib import Path
from typing import Optional

from src.common.logger import get_logger
from src.extraction import ExtractedContent, ContentBlock
from src.search import MatchInfo


class PreviewRenderer:
    """プレビューレンダラー"""
    
    # スタイル定義
    BASE_STYLE = """
    <style>
        body {
            font-family: 'Segoe UI', 'Yu Gothic UI', 'Meiryo', sans-serif;
            font-size: 14px;
            line-height: 1.6;
            padding: 16px;
            margin: 0;
            background-color: #ffffff;
            color: #333333;
        }
        .match-highlight {
            background-color: #ffeb3b;
            padding: 2px 4px;
            border-radius: 2px;
            font-weight: bold;
        }
        .page-header {
            background-color: #f5f5f5;
            padding: 8px 12px;
            margin: 16px 0 8px 0;
            border-left: 4px solid #2196f3;
            font-weight: bold;
            color: #666;
        }
        .sheet-header {
            background-color: #e8f5e9;
            padding: 8px 12px;
            margin: 16px 0 8px 0;
            border-left: 4px solid #4caf50;
            font-weight: bold;
            color: #666;
        }
        .slide-header {
            background-color: #fff3e0;
            padding: 8px 12px;
            margin: 16px 0 8px 0;
            border-left: 4px solid #ff9800;
            font-weight: bold;
            color: #666;
        }
        .content-block {
            margin: 8px 0;
            padding: 4px 0;
        }
        .line-number {
            color: #999;
            font-size: 12px;
            margin-right: 8px;
            user-select: none;
        }
        table {
            border-collapse: collapse;
            margin: 8px 0;
        }
        td, th {
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }
        th {
            background-color: #f5f5f5;
        }
        .encoding-info {
            position: fixed;
            bottom: 8px;
            right: 8px;
            background-color: rgba(0, 0, 0, 0.6);
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
        }
        pre {
            background-color: #f8f8f8;
            padding: 12px;
            border-radius: 4px;
            overflow-x: auto;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
    </style>
    """
    
    def __init__(self):
        self._logger = get_logger("preview")
    
    def render_match(
        self,
        match: MatchInfo,
        content: ExtractedContent,
    ) -> str:
        """マッチ箇所を中心にHTMLをレンダリング
        
        Args:
            match: マッチ情報
            content: 抽出されたコンテンツ
        
        Returns:
            HTML文字列
        """
        html_parts = [
            "<!DOCTYPE html>",
            "<html><head><meta charset='utf-8'>",
            self.BASE_STYLE,
            "</head><body>",
        ]
        
        # マッチ箇所のテキストをハイライト
        highlighted_text = self._highlight_text(
            match.text,
            match.start,
            match.end,
        )
        
        # 位置情報ヘッダー
        location = match.get_location_info()
        html_parts.append(f'<div class="page-header">{html.escape(location)}</div>')
        
        # コンテンツ
        html_parts.append(f'<div class="content-block">{highlighted_text}</div>')
        
        # 文字コード表示（テキスト系の場合）
        if content.encoding:
            html_parts.append(f'<div class="encoding-info">{html.escape(content.encoding)}</div>')
        
        html_parts.append("</body></html>")
        
        return "\n".join(html_parts)
    
    def render_full(
        self,
        content: ExtractedContent,
        matches: Optional[list[MatchInfo]] = None,
        page_filter: Optional[int] = None,
        sheet_filter: Optional[str] = None,
    ) -> str:
        """ファイル全体をHTMLでレンダリング（フルロード）
        
        Args:
            content: 抽出されたコンテンツ
            matches: マッチ情報（ハイライト用）
            page_filter: 特定ページのみ表示
            sheet_filter: 特定シートのみ表示
        
        Returns:
            HTML文字列
        """
        html_parts = [
            "<!DOCTYPE html>",
            "<html><head><meta charset='utf-8'>",
            self.BASE_STYLE,
            "</head><body>",
        ]
        
        # マッチ位置のセットを作成（高速検索用）
        match_positions = self._build_match_positions(matches) if matches else {}
        
        # ブロックをグループ化（ページ/シート/スライド単位）
        current_page = None
        current_sheet = None
        current_slide = None
        
        for block in content.blocks:
            # フィルタリング
            if page_filter is not None and block.page != page_filter:
                continue
            if sheet_filter is not None and block.sheet != sheet_filter:
                continue
            
            # ページヘッダー
            if block.page is not None and block.page != current_page:
                current_page = block.page
                html_parts.append(f'<div class="page-header">ページ {current_page}</div>')
            
            # シートヘッダー
            if block.sheet is not None and block.sheet != current_sheet:
                current_sheet = block.sheet
                html_parts.append(f'<div class="sheet-header">シート: {html.escape(current_sheet)}</div>')
            
            # スライドヘッダー
            if block.slide is not None and block.slide != current_slide:
                current_slide = block.slide
                html_parts.append(f'<div class="slide-header">スライド {current_slide}</div>')
            
            # コンテンツブロック
            block_html = self._render_block(block, match_positions)
            html_parts.append(block_html)
        
        # 文字コード表示（テキスト系の場合）
        if content.encoding:
            html_parts.append(f'<div class="encoding-info">{html.escape(content.encoding)}</div>')
        
        html_parts.append("</body></html>")
        
        return "\n".join(html_parts)
    
    def render_page(
        self,
        content: ExtractedContent,
        page: int,
        matches: Optional[list[MatchInfo]] = None,
    ) -> str:
        """特定ページをレンダリング"""
        return self.render_full(content, matches, page_filter=page)
    
    def render_sheet(
        self,
        content: ExtractedContent,
        sheet: str,
        matches: Optional[list[MatchInfo]] = None,
    ) -> str:
        """特定シートをレンダリング"""
        return self.render_full(content, matches, sheet_filter=sheet)
    
    def _render_block(
        self,
        block: ContentBlock,
        match_positions: dict,
    ) -> str:
        """ブロックをHTMLにレンダリング"""
        text = block.text
        
        # マッチ箇所をハイライト
        if block in match_positions:
            positions = match_positions[block]
            text = self._highlight_multiple(text, positions)
        else:
            text = html.escape(text)
        
        # 行番号表示
        line_prefix = ""
        if block.line is not None:
            line_prefix = f'<span class="line-number">{block.line}</span>'
        
        # セル参照表示
        cell_prefix = ""
        if block.cell is not None:
            cell_prefix = f'<span class="line-number">[{block.cell}]</span>'
        
        return f'<div class="content-block">{line_prefix}{cell_prefix}{text}</div>'
    
    def _highlight_text(self, text: str, start: int, end: int) -> str:
        """テキストの一部をハイライト"""
        before = html.escape(text[:start])
        matched = html.escape(text[start:end])
        after = html.escape(text[end:])
        
        return f'{before}<span class="match-highlight">{matched}</span>{after}'
    
    def _highlight_multiple(self, text: str, positions: list[tuple[int, int]]) -> str:
        """複数箇所をハイライト"""
        # 位置でソート（逆順）
        sorted_positions = sorted(positions, key=lambda x: x[0], reverse=True)
        
        # 後ろから置換（位置がずれないように）
        result = text
        for start, end in sorted_positions:
            matched = result[start:end]
            result = (
                result[:start] +
                f'<span class="match-highlight">{html.escape(matched)}</span>' +
                result[end:]
            )
        
        # まだエスケープされていない部分をエスケープ
        # （ハイライト部分以外）
        # 注: この実装は簡易版。完全な実装では正規表現で処理
        
        return result
    
    def _build_match_positions(
        self,
        matches: list[MatchInfo],
    ) -> dict[ContentBlock, list[tuple[int, int]]]:
        """マッチ位置のマップを構築"""
        positions: dict[ContentBlock, list[tuple[int, int]]] = {}
        
        for match in matches:
            if match.block not in positions:
                positions[match.block] = []
            positions[match.block].append((match.start, match.end))
        
        return positions
