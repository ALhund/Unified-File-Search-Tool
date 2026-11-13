"""検索用の文字正規化

全角/半角（ＡＢＣ⇔ABC、ｶﾀｶﾅ⇔カタカナ）や大文字/小文字の違いを吸収した
「照合用文字列」を作り、照合結果の位置を元の文字列の位置へ戻せるようにする。

大半のテキストは正規化しても長さが変わらないので、その場合は位置対応表を
作らない高速経路を通す（対応表が必要なのは半角カナや合字を含むときだけ）。
"""

import unicodedata
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FoldedText:
    """照合用に正規化した文字列と、元の位置への対応"""

    text: str
    # starts[i] / ends[i] は、正規化後の i 文字目が元の文字列のどの範囲に対応するか。
    # None の場合は位置がそのまま一致する。
    starts: Optional[tuple[int, ...]] = None
    ends: Optional[tuple[int, ...]] = None

    def span(self, start: int, end: int) -> tuple[int, int]:
        """正規化後の範囲 [start, end) を元の文字列の範囲に変換"""
        if self.starts is None or end <= start:
            return start, end
        return self.starts[start], self.ends[end - 1]


def fold_text(text: str, ignore_case: bool, ignore_width: bool) -> FoldedText:
    """照合用に正規化する"""
    if not ignore_case and not ignore_width:
        return FoldedText(text)

    # 高速経路: 正規化で文字数が変わらないケース
    if not ignore_width or text.isascii() or unicodedata.is_normalized("NFKC", text):
        folded = text.lower() if ignore_case else text
        if len(folded) == len(text):
            return FoldedText(folded)

    return _fold_slow(text, ignore_case, ignore_width)


def _fold_slow(text: str, ignore_case: bool, ignore_width: bool) -> FoldedText:
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []

    for i, ch in enumerate(text):
        piece = unicodedata.normalize("NFKC", ch) if ignore_width else ch
        if ignore_case:
            piece = piece.lower()
        for c in piece:
            # 半角カナの濁点・半濁点などは直前の文字と合成する（ｶﾞ → ガ）
            if out and unicodedata.combining(c):
                composed = unicodedata.normalize("NFC", out[-1] + c)
                if len(composed) == 1:
                    out[-1] = composed
                    ends[-1] = i + 1
                    continue
            out.append(c)
            starts.append(i)
            ends.append(i + 1)

    return FoldedText("".join(out), tuple(starts), tuple(ends))


def fold_query(query: str, ignore_case: bool, ignore_width: bool) -> str:
    """検索語側を同じ規則で正規化する"""
    return fold_text(query, ignore_case, ignore_width).text


def _is_wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F", "H")


def join_wrapped_lines(lines: list[str]) -> str:
    """折り返された行を1つの文字列に連結する

    日本語は折り返し位置に空白を入れずに連結し（「バナ」「ナ」→「バナナ」）、
    欧文は空白1つで連結する。PDFのテキスト抽出とプレビューのハイライトで
    同じ規則を使うことで、行をまたぐ語も検索・強調できる。
    """
    result: list[str] = []
    prev = ""
    for line in lines:
        if not line:
            continue
        if prev:
            result.append(line_separator(prev[-1], line[0]))
        result.append(line)
        prev = line
    return "".join(result)


def line_separator(prev_char: str, next_char: str) -> str:
    """行の継ぎ目に入れる文字（日本語同士なら空文字、それ以外は空白）"""
    if prev_char.isspace() or next_char.isspace():
        return ""
    if _is_wide(prev_char) and _is_wide(next_char):
        return ""
    return " "
