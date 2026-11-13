"""ライセンスコードの形式・署名・検証

コードの中身（72バイト）を Base32 で文字にしたもの:
    形式番号(1) + ライセンス番号(4) + 発行日(2: 2020-01-01 からの日数) + 製品版(1) + 署名(64)

署名（Ed25519）の対象には購入者名も含めるため、コードは発行した名前でしか使えない。
アプリには公開鍵だけを入れ、署名に使う秘密鍵は販売者だけが持つ。
"""

import base64
import re
import struct
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

PREFIX = "UFS1"
FORMAT_VERSION = 1
EPOCH = date(2020, 1, 1)
_PAYLOAD = struct.Struct(">BIHB")
SIGNATURE_SIZE = 64
GROUP = 6
_DOMAIN = b"UnifiedFileSearch-License-v1|"
_ENCODED_LENGTH = -(-(_PAYLOAD.size + SIGNATURE_SIZE) * 8 // 5)  # Base32 の文字数（パディングなし）


class LicenseError(ValueError):
    """コードが正しくない（利用者に見せるメッセージを持つ）"""


@dataclass(frozen=True)
class LicenseInfo:
    name: str
    license_id: int
    issued: date
    edition: int


def normalize_name(name: str) -> str:
    """名前の表記ゆれ（全角/半角・空白・大文字/小文字）を吸収する"""
    text = unicodedata.normalize("NFKC", name)
    return "".join(text.split()).casefold()


def _message(payload: bytes, name: str) -> bytes:
    return _DOMAIN + payload + b"|" + normalize_name(name).encode("utf-8")


def _encode(data: bytes) -> str:
    text = base64.b32encode(data).decode("ascii").rstrip("=")
    groups = [text[i:i + GROUP] for i in range(0, len(text), GROUP)]
    return "-".join([PREFIX] + groups)


def _decode(code: str) -> bytes:
    # コピー＆ペーストで混ざりやすい空白・改行・全角文字・区切りを取り除く
    text = unicodedata.normalize("NFKC", code).upper()
    text = re.sub(r"[^A-Z0-9]", "", text)
    if not text.startswith(PREFIX):
        raise LicenseError("ライセンスコードの形式が正しくありません（UFS1- で始まるコードを入力してください）")
    text = text[len(PREFIX):]
    # 読み間違えやすい文字を補正する（Base32 は 0, 1, 8, 9 を使わない）
    text = text.translate(str.maketrans({"0": "O", "1": "I", "8": "B"}))
    if len(text) != _ENCODED_LENGTH:
        raise LicenseError("ライセンスコードの長さが正しくありません（途中で切れていないか確認してください）")
    try:
        return base64.b32decode(text + "=" * (-len(text) % 8))
    except (ValueError, base64.binascii.Error) as e:
        raise LicenseError("ライセンスコードに使えない文字が含まれています") from e


def issue_code(private_key, name: str, license_id: int, edition: int = 1, issued: Optional[date] = None) -> str:
    """ライセンスコードを発行する（販売者の生成ツール用）"""
    if not normalize_name(name):
        raise LicenseError("購入者名を入力してください")
    if not 0 < license_id < 2 ** 32:
        raise LicenseError("ライセンス番号が範囲外です")
    issued = issued or date.today()
    payload = _PAYLOAD.pack(FORMAT_VERSION, license_id, (issued - EPOCH).days, edition)
    signature = private_key.sign(_message(payload, name))
    return _encode(payload + signature)


def verify_code(public_key, name: str, code: str, revoked: frozenset[int] = frozenset()) -> LicenseInfo:
    """コードを検証する（正しくなければ LicenseError）"""
    from cryptography.exceptions import InvalidSignature
    
    if not normalize_name(name):
        raise LicenseError("登録名を入力してください")
    data = _decode(code)
    if len(data) != _PAYLOAD.size + SIGNATURE_SIZE:
        raise LicenseError("ライセンスコードの長さが正しくありません（途中で切れていないか確認してください）")
    payload, signature = data[:_PAYLOAD.size], data[_PAYLOAD.size:]
    version, license_id, days, edition = _PAYLOAD.unpack(payload)
    if version != FORMAT_VERSION:
        raise LicenseError("このバージョンのアプリでは使えないライセンスコードです")
    try:
        public_key.verify(signature, _message(payload, name))
    except InvalidSignature as e:
        raise LicenseError(
            "ライセンスコードと登録名が一致しません。購入時にお知らせした登録名とコードを、そのまま入力してください"
        ) from e
    if license_id in revoked:
        raise LicenseError("このライセンスコードは無効になっています。購入先にお問い合わせください")
    return LicenseInfo(name=name.strip(), license_id=license_id, issued=EPOCH + timedelta(days=days), edition=edition)


def load_public_key(b64: str):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(b64))


def generate_private_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.generate()


def public_key_b64(private_key) -> str:
    from cryptography.hazmat.primitives import serialization
    raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode("ascii")
