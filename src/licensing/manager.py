"""ライセンスの状態（体験版・登録済み）の管理

登録情報と体験版の開始日は、利用者ごとのフォルダ
（Windows では %LOCALAPPDATA%\\Unified-File-Search-Tool\\license.json）に保存する。
アプリを入れ直しても登録は残る。
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from src.licensing import policy
from src.licensing.codec import LicenseError, LicenseInfo, load_public_key, verify_code
from src.licensing.public_key import PUBLIC_KEY_B64
from src.licensing.revoked import REVOKED_LICENSE_IDS


@dataclass
class LicenseState:
    status: str  # licensed / trial / expired / unconfigured
    info: Optional[LicenseInfo] = None
    trial_days_left: int = 0
    
    @property
    def can_search(self) -> bool:
        return self.status in ("licensed", "trial", "unconfigured")
    
    @property
    def edition_name(self) -> str:
        if self.info is None:
            return ""
        return policy.EDITIONS.get(self.info.edition, f"製品版 {self.info.edition}")
    
    def summary(self) -> str:
        """画面に出す一行の説明"""
        if self.status == "licensed" and self.info:
            return f"登録済み: {self.info.name} 様（{self.edition_name}・No.{self.info.license_id}）"
        if self.status == "trial":
            return f"体験版: 残り {self.trial_days_left} 日"
        if self.status == "expired":
            return "体験期間が終了しました"
        return "開発版（ライセンス未設定）"


def default_storage() -> Path:
    from src.common.config import Config
    return Config.get_user_base() / "license.json"


class LicenseManager:
    """ライセンスの読み込み・登録・解除"""
    
    def __init__(self, storage: Optional[Path] = None, public_key_b64: Optional[str] = None,
                 today: Optional[date] = None):
        self._storage = storage or default_storage()
        key = PUBLIC_KEY_B64 if public_key_b64 is None else public_key_b64
        self._public_key = load_public_key(key) if key else None
        self._today = today
    
    # ------------------------------------------------------------------
    
    def _now(self) -> date:
        return self._today or date.today()
    
    def _load(self) -> dict:
        try:
            data = json.loads(self._storage.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}
    
    def _save(self, data: dict) -> None:
        self._storage.parent.mkdir(parents=True, exist_ok=True)
        temp = self._storage.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self._storage)
    
    @property
    def configured(self) -> bool:
        return self._public_key is not None
    
    def state(self) -> LicenseState:
        if not self.configured:
            return LicenseState("unconfigured")
        
        data = self._load()
        name, code = data.get("name"), data.get("code")
        if name and code:
            try:
                info = verify_code(self._public_key, name, code, frozenset(REVOKED_LICENSE_IDS))
                return LicenseState("licensed", info)
            except LicenseError:
                pass  # 不正・無効化されたコードは体験版として扱う
        
        return self._trial_state(data)
    
    def _trial_state(self, data: dict) -> LicenseState:
        today = self._now()
        changed = False
        try:
            started = date.fromisoformat(data["trial_started"])
        except (KeyError, TypeError, ValueError):
            started = today
            data["trial_started"] = started.isoformat()
            changed = True
        # 時計を戻して体験期間を延ばせないよう、最後に使った日を覚えておく
        try:
            last_seen = date.fromisoformat(data.get("last_seen", ""))
        except ValueError:
            last_seen = today
        effective = max(today, last_seen)
        if data.get("last_seen") != effective.isoformat():
            data["last_seen"] = effective.isoformat()
            changed = True
        if changed:
            try:
                self._save(data)
            except OSError:
                pass
        
        used = (effective - started).days
        left = policy.TRIAL_DAYS - used
        if left > 0:
            return LicenseState("trial", trial_days_left=left)
        return LicenseState("expired")
    
    def activate(self, name: str, code: str) -> LicenseInfo:
        """コードを登録する（正しくなければ LicenseError）"""
        if not self.configured:
            raise LicenseError("この版はライセンスの登録に対応していません")
        info = verify_code(self._public_key, name, code, frozenset(REVOKED_LICENSE_IDS))
        data = self._load()
        data.update({
            "name": name.strip(),
            "code": code.strip(),
            "activated_at": datetime.now().isoformat(timespec="seconds"),
        })
        self._save(data)
        return info
    
    def deactivate(self) -> None:
        """登録を解除する（別のパソコンへ移すときなど）"""
        data = self._load()
        for key in ("name", "code", "activated_at"):
            data.pop(key, None)
        self._save(data)
    
    def trial_expires_on(self) -> Optional[date]:
        data = self._load()
        try:
            return date.fromisoformat(data["trial_started"]) + timedelta(days=policy.TRIAL_DAYS)
        except (KeyError, TypeError, ValueError):
            return None
