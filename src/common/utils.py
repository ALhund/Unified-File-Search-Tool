"""ユーティリティモジュール。

文字正規化、制御文字処理、文字コード判別などのアプリ横断的な共通処理を提供する。
"""

import re

import chardet


def normalize_newlines(text: str) -> str:
    """改行コードを ``\\n`` (LF) に統一する。

    CR LF (``\\r\\n``) および CR (``\\r``) を LF (``\\n``) に変換する。

    Args:
        text: 正規化対象のテキスト。

    Returns:
        改行コードを統一したテキスト。
    """
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")
    return text


def sanitize_control_chars(text: str, keep_newlines: bool = True) -> str:
    """ASCII 制御文字を除去する。

    Args:
        text: 処理対象のテキスト。
        keep_newlines: ``True`` の場合、タブ（``\\x09``）・LF（``\\x0a``）・
                       CR（``\\x0d``）は保持する。

    Returns:
        制御文字を除去したテキスト。
    """
    if keep_newlines:
        # タブ・LF・CR 以外の制御文字を除去
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return re.sub(r"[\x00-\x1f]", "", text)


def strip_leading_whitespace_per_line(text: str) -> str:
    """各行の行頭空白・タブを除去して左詰めにする。

    Args:
        text: 処理対象のテキスト。

    Returns:
        各行を左詰めにしたテキスト。
    """
    return "\n".join(line.lstrip() for line in text.split("\n"))


def detect_encoding(data: bytes) -> str:
    """バイト列の文字コードを判別する（日本語前提、CP932 優先）。

    判別優先順:

    1. BOM チェック（UTF-8 BOM / UTF-16 BOM）
    2. CP932 として厳密デコードを試みる
    3. UTF-8 として厳密デコードを試みる
    4. chardet による自動判別
    5. 上記いずれも失敗した場合は CP932 を返す（文字化け許容）

    Args:
        data: 文字コード判別対象のバイト列。

    Returns:
        判別された文字コード名（例: ``"utf-8"``, ``"cp932"``, ``"euc-jp"``）。
    """
    # BOM チェック
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return "utf-16"

    # CP932 を試みる
    try:
        data.decode("cp932")
        return "cp932"
    except UnicodeDecodeError:
        pass

    # UTF-8 を試みる
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    # chardet で自動判別
    result = chardet.detect(data)
    detected: str | None = result.get("encoding")

    if detected:
        detected_lower = detected.lower()
        if detected_lower in ("shift_jis", "shift-jis", "sjis", "windows-31j"):
            return "cp932"
        if detected_lower in ("euc-jp", "euc_jp", "eucjp"):
            return "euc-jp"
        if detected_lower.startswith("utf"):
            return detected_lower.replace("-", "_")
        return detected

    return "cp932"


def decode_with_fallback(
    data: bytes,
    preferred_encoding: str | None = None,
) -> tuple[str, str]:
    """バイト列を文字列にデコードする（文字化け許容フォールバック付き）。

    Args:
        data: デコード対象のバイト列。
        preferred_encoding: 優先して試みるエンコーディング。
                            ``None`` の場合は :func:`detect_encoding` で自動判別する。

    Returns:
        ``(デコードされた文字列, 使用したエンコーディング名)`` のタプル。
    """
    encoding = preferred_encoding or detect_encoding(data)

    try:
        return data.decode(encoding), encoding
    except (UnicodeDecodeError, LookupError):
        pass

    # フォールバック 1: CP932（置換モード）
    try:
        return data.decode("cp932", errors="replace"), "cp932"
    except (UnicodeDecodeError, LookupError):
        pass

    # フォールバック 2: UTF-8（置換モード）
    return data.decode("utf-8", errors="replace"), "utf-8"


def format_file_size(size_bytes: int) -> str:
    """ファイルサイズを人間が読みやすい文字列にフォーマットする。

    Args:
        size_bytes: バイト単位のファイルサイズ。

    Returns:
        例: ``"1.5 MB"``, ``"234 B"``, ``"3.2 GB"``
    """
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            if unit == "B":
                return f"{size_bytes} {unit}"
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} TB"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """テキストを指定の最大長で切り詰める。

    Args:
        text: 対象テキスト。
        max_length: 返す文字列の最大長（suffix を含む）。
        suffix: 切り詰め時に末尾に付加する文字列。

    Returns:
        ``max_length`` 以内のテキスト。切り詰めた場合は末尾に ``suffix`` を付ける。
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix
