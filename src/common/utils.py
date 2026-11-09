"""ユーティリティモジュール

文字正規化、制御文字処理、文字コード判別などの共通処理。
"""

import re
import threading
from typing import Optional
import chardet

# PyMuPDF はスレッドセーフではないため、同一プロセス内の呼び出しはこのロックで直列化する
FITZ_LOCK = threading.RLock()


def normalize_newlines(text: str) -> str:
    """改行コードを\\nに正規化する
    
    CR LF (\\r\\n) → LF (\\n)
    CR (\\r) → LF (\\n)
    """
    # まず CRLF を LF に
    text = text.replace("\r\n", "\n")
    # 残った CR を LF に
    text = text.replace("\r", "\n")
    return text


def sanitize_control_chars(text: str, keep_newlines: bool = True) -> str:
    """制御文字を除去する
    
    Args:
        text: 処理対象のテキスト
        keep_newlines: Trueの場合、改行文字は保持する
    
    Returns:
        制御文字を除去したテキスト
    """
    if keep_newlines:
        # 改行以外の制御文字を除去（\\x00-\\x08, \\x0b, \\x0c, \\x0e-\\x1f）
        # \\x09 = タブ, \\x0a = LF, \\x0d = CR は保持
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    else:
        # すべての制御文字を除去
        return re.sub(r"[\x00-\x1f]", "", text)


def strip_leading_whitespace_per_line(text: str) -> str:
    """各行の行頭空白/タブを除去して左詰めにする"""
    lines = text.split("\n")
    stripped_lines = [line.lstrip() for line in lines]
    return "\n".join(stripped_lines)


def detect_encoding(data: bytes) -> str:
    """文字コードを判別する（日本語前提）
    
    判別順:
    1. BOM付きUTF
    2. ASCIIのみ → CP932（表示上の違いはない）
    3. UTF-8として厳密に正しい → UTF-8
       （CP932の文章が偶然UTF-8として正しくなることはまずないが、
         逆にUTF-8の文章はCP932としても「読めてしまう」ことがあるため先に判定する）
    4. CP932（Windows-932）
    5. chardetによる推定、それでも不可ならCP932（文字化け許容）
    
    Returns:
        判別された文字コード名
    """
    # BOMチェック（UTF系の明示的なマーカー）
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return "utf-16"
    
    if data.isascii():
        return "cp932"
    
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    
    try:
        data.decode("cp932")
        return "cp932"
    except UnicodeDecodeError:
        pass
    
    # chardetで自動判別（大きなファイルは先頭だけで判定する）
    result = chardet.detect(data[:200_000])
    detected = result.get("encoding")
    
    if detected:
        # 日本語エンコーディングの正規化
        detected_lower = detected.lower()
        if detected_lower in ("shift_jis", "shift-jis", "sjis", "windows-31j"):
            return "cp932"
        if detected_lower in ("euc-jp", "euc_jp", "eucjp"):
            return "euc-jp"
        return detected_lower
    
    # 判別不能な場合はCP932（文字化け許容）
    return "cp932"


def decode_with_fallback(data: bytes, preferred_encoding: Optional[str] = None) -> tuple[str, str]:
    """バイトデータを文字列にデコードする（文字化け許容）
    
    Args:
        data: デコード対象のバイトデータ
        preferred_encoding: 優先するエンコーディング（Noneの場合は自動判別）
    
    Returns:
        (デコードされた文字列, 使用したエンコーディング)
    """
    encoding = preferred_encoding or detect_encoding(data)
    
    try:
        text = data.decode(encoding)
        return text, encoding
    except (UnicodeDecodeError, LookupError):
        pass
    
    # フォールバック: CP932
    try:
        text = data.decode("cp932", errors="replace")
        return text, "cp932"
    except (UnicodeDecodeError, LookupError):
        pass
    
    # 最終フォールバック: UTF-8（置換モード）
    text = data.decode("utf-8", errors="replace")
    return text, "utf-8"


def format_file_size(size_bytes: int) -> str:
    """ファイルサイズを人間が読みやすい形式にフォーマット"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """テキストを指定長で切り詰める"""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix
