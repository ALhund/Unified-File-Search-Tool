from src.common.textnorm import fold_text, join_wrapped_lines


def test_ascii_fast_path_has_no_map():
    folded = fold_text("Hello World", True, True)
    assert folded.text == "hello world"
    assert folded.starts is None
    assert folded.span(6, 11) == (6, 11)


def test_fullwidth_alnum_is_folded():
    folded = fold_text("ＡＢＣ商事", True, True)
    assert folded.text == "abc商事"
    assert folded.span(0, 3) == (0, 3)


def test_halfwidth_kana_with_dakuten_maps_back_to_original_span():
    text = "xｶﾞｷﾞy"  # ｶ+ﾞ, ｷ+ﾞ → ガギ
    folded = fold_text(text, True, True)
    assert folded.text == "xガギy"
    start = folded.text.index("ガギ")
    assert folded.span(start, start + 2) == (1, 5)
    assert text[1:5] == "ｶﾞｷﾞ"


def test_expanding_character_maps_to_single_original():
    text = "㍻元年"  # ㍻ → 平成
    folded = fold_text(text, False, True)
    assert folded.text == "平成元年"
    assert folded.span(0, 2) == (0, 1)
    assert folded.span(1, 3) == (0, 2)


def test_width_sensitive_keeps_text():
    assert fold_text("ＡＢＣ", False, False).text == "ＡＢＣ"
    assert fold_text("ＡＢＣ", True, False).text == "ａｂｃ"


def test_join_wrapped_lines():
    assert join_wrapped_lines(["検索対象バナ", "ナです"]) == "検索対象バナナです"
    assert join_wrapped_lines(["hello", "world"]) == "hello world"
    assert join_wrapped_lines(["価格", "100円"]) == "価格 100円"
    assert join_wrapped_lines(["a", "", "b"]) == "a b"
