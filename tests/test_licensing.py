from datetime import date, timedelta

import pytest

from src.licensing import policy
from src.licensing.codec import (
    LicenseError,
    generate_private_key,
    issue_code,
    public_key_b64,
    verify_code,
)
from src.licensing.manager import LicenseManager


@pytest.fixture
def keys():
    private = generate_private_key()
    return private, public_key_b64(private)


def test_issue_and_verify(keys):
    private, _ = keys
    code = issue_code(private, "山田 太郎", 123, issued=date(2026, 11, 13))
    assert code.startswith("UFS1-")
    info = verify_code(private.public_key(), "山田 太郎", code)
    assert (info.license_id, info.issued, info.edition) == (123, date(2026, 11, 13), 1)


def test_name_variations_are_accepted(keys):
    private, _ = keys
    code = issue_code(private, "Yamada Taro", 7)
    # 空白・全角・大文字小文字の違い、改行やスペースの混入、小文字のコード
    pasted = "\n  " + code.lower().replace("-", " - ") + "  \n"
    assert verify_code(private.public_key(), "ｙａｍａｄａ　taro", pasted).license_id == 7


def test_wrong_name_or_tampered_code_is_rejected(keys):
    private, _ = keys
    code = issue_code(private, "山田太郎", 1)
    with pytest.raises(LicenseError, match="一致しません"):
        verify_code(private.public_key(), "山田花子", code)
    tampered = code[:-3] + ("A" if code[-3] != "A" else "B") + code[-2:]
    with pytest.raises(LicenseError):
        verify_code(private.public_key(), "山田太郎", tampered)
    with pytest.raises(LicenseError, match="長さ"):
        verify_code(private.public_key(), "山田太郎", code[:40])
    with pytest.raises(LicenseError, match="形式"):
        verify_code(private.public_key(), "山田太郎", "ABCD-EFGH")


def test_code_from_other_key_is_rejected(keys):
    private, _ = keys
    other = generate_private_key()
    code = issue_code(other, "山田太郎", 1)
    with pytest.raises(LicenseError):
        verify_code(private.public_key(), "山田太郎", code)


def test_revoked_code_is_rejected(keys):
    private, _ = keys
    code = issue_code(private, "山田太郎", 99)
    with pytest.raises(LicenseError, match="無効"):
        verify_code(private.public_key(), "山田太郎", code, revoked=frozenset({99}))


def test_trial_then_expired_then_activated(tmp_path, keys):
    private, public = keys
    storage = tmp_path / "license.json"
    start = date(2026, 1, 1)
    
    state = LicenseManager(storage, public, today=start).state()
    assert state.status == "trial" and state.trial_days_left == policy.TRIAL_DAYS and state.can_search
    
    later = LicenseManager(storage, public, today=start + timedelta(days=policy.TRIAL_DAYS - 1)).state()
    assert later.status == "trial" and later.trial_days_left == 1
    
    expired = LicenseManager(storage, public, today=start + timedelta(days=policy.TRIAL_DAYS))
    assert expired.state().status == "expired" and not expired.state().can_search
    
    # 時計を戻しても体験期間は戻らない
    assert LicenseManager(storage, public, today=start).state().status == "expired"
    
    with pytest.raises(LicenseError):
        expired.activate("山田太郎", issue_code(private, "別の人", 5))
    expired.activate("山田太郎", issue_code(private, "山田太郎", 5))
    state = LicenseManager(storage, public).state()
    assert state.status == "licensed" and state.info.name == "山田太郎" and state.can_search
    assert "山田太郎 様" in state.summary()
    
    expired.deactivate()
    assert LicenseManager(storage, public, today=start + timedelta(days=30)).state().status == "expired"


def test_unconfigured_build_is_unrestricted(tmp_path):
    manager = LicenseManager(tmp_path / "license.json", public_key_b64="")
    assert manager.state().status == "unconfigured" and manager.state().can_search
    with pytest.raises(LicenseError):
        manager.activate("a", "UFS1-AAAA")


def test_parse_pasted_buyer_message():
    pytest.importorskip("PySide6.QtWidgets")
    import sys
    sys.path.insert(0, ".")
    from tools.license_generator import BUYER_MESSAGE
    from src.ui.widgets.license_dialog import parse_pasted
    
    code = "UFS1-" + "-".join(["ABCDEF"] * 20)
    message = BUYER_MESSAGE.format(name="山田 太郎", code=code)
    assert parse_pasted(message) == ("山田 太郎", code)
    assert parse_pasted("登録名：佐藤\r\nライセンスコード：" + code) == ("佐藤", code)
    assert parse_pasted(code) == ("", code)
