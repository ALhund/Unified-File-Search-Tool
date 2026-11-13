"""利用者ごとの設定（前回のフォルダ・履歴・テーマなど）

Windows ではレジストリ（HKCU\\Software\\UnifiedFileSearchTool）に保存される。
Config/config.xml は既定値、こちらは利用者が画面で変えた値を保持する。
"""

from typing import Any, Optional

from PySide6.QtCore import QSettings

ORGANIZATION = "UnifiedFileSearchTool"
APPLICATION = "UnifiedFileSearchTool"
MAX_HISTORY = 15

# 1ファイルあたりのヒット数の上限の選択肢（0 = 無制限）
MATCH_LIMIT_CHOICES = [50, 100, 500, 1000, 5000, 0]


class UserSettings:
    """QSettings の薄いラッパー（型を揃えて読み書きする）"""
    
    def __init__(self, settings: Optional[QSettings] = None):
        self._s = settings or QSettings(ORGANIZATION, APPLICATION)
    
    def _get(self, key: str, default: Any, kind: type) -> Any:
        value = self._s.value(key, default)
        if value is None:
            return default
        try:
            if kind is bool:
                return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
            if kind is list:
                if isinstance(value, str):
                    return [value] if value else []
                return list(value)
            return kind(value)
        except (TypeError, ValueError):
            return default
    
    def _set(self, key: str, value: Any) -> None:
        self._s.setValue(key, value)
    
    # --- 外観 ---
    @property
    def theme(self) -> str:
        return self._get("appearance/theme", "system", str)
    
    @theme.setter
    def theme(self, value: str) -> None:
        self._set("appearance/theme", value)
    
    @property
    def use_system_accent(self) -> bool:
        return self._get("appearance/system_accent", True, bool)
    
    @use_system_accent.setter
    def use_system_accent(self, value: bool) -> None:
        self._set("appearance/system_accent", value)
    
    # --- 検索 ---
    @property
    def last_folder(self) -> str:
        return self._get("search/last_folder", "", str)
    
    @last_folder.setter
    def last_folder(self, value: str) -> None:
        self._set("search/last_folder", value)
    
    @property
    def recent_folders(self) -> list[str]:
        return self._get("search/recent_folders", [], list)
    
    def add_recent_folder(self, folder: str) -> None:
        self._set("search/recent_folders", _push(self.recent_folders, folder))
        self.last_folder = folder
    
    @property
    def query_history(self) -> list[str]:
        return self._get("search/query_history", [], list)
    
    def add_query(self, query: str) -> None:
        self._set("search/query_history", _push(self.query_history, query))
    
    def clear_history(self) -> None:
        self._set("search/query_history", [])
        self._set("search/recent_folders", [])
    
    @property
    def search_state(self) -> dict:
        """前回の検索条件（チェック状態など）"""
        value = self._s.value("search/state", {})
        return dict(value) if isinstance(value, dict) else {}
    
    @search_state.setter
    def search_state(self, value: dict) -> None:
        self._set("search/state", value)
    
    @property
    def match_limit(self) -> Optional[int]:
        """1ファイルあたりの上限（未設定なら None = config.xml の値）"""
        value = self._s.value("search/match_limit")
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None
    
    @match_limit.setter
    def match_limit(self, value: int) -> None:
        self._set("search/match_limit", int(value))
    
    @property
    def workers(self) -> Optional[int]:
        value = self._s.value("search/workers")
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None
    
    @workers.setter
    def workers(self, value: int) -> None:
        self._set("search/workers", int(value))
    
    @property
    def export_folder(self) -> str:
        return self._get("search/export_folder", "", str)
    
    @export_folder.setter
    def export_folder(self, value: str) -> None:
        self._set("search/export_folder", value)
    
    # --- 常時インデックス ---
    @property
    def index_enabled(self) -> bool:
        return self._get("index/enabled", True, bool)
    
    @index_enabled.setter
    def index_enabled(self, value: bool) -> None:
        self._set("index/enabled", value)
    
    @property
    def index_folders(self) -> list[str]:
        return self._get("index/folders", [], list)
    
    @index_folders.setter
    def index_folders(self, folders: list[str]) -> None:
        unique: list[str] = []
        for folder in folders:
            if folder and folder not in unique:
                unique.append(folder)
        self._set("index/folders", unique)
    
    @property
    def index_auto_add(self) -> bool:
        """検索したフォルダを自動で常時インデックスに加える"""
        return self._get("index/auto_add", True, bool)
    
    @index_auto_add.setter
    def index_auto_add(self, value: bool) -> None:
        self._set("index/auto_add", value)
    
    @property
    def index_interval_min(self) -> int:
        return self._get("index/interval_min", 15, int)
    
    @index_interval_min.setter
    def index_interval_min(self, value: int) -> None:
        self._set("index/interval_min", int(value))
    
    @property
    def tray_on_close(self) -> bool:
        """閉じてもタスクトレイに常駐して索引を更新し続ける"""
        return self._get("app/tray_on_close", True, bool)
    
    @tray_on_close.setter
    def tray_on_close(self, value: bool) -> None:
        self._set("app/tray_on_close", value)
    
    @property
    def tray_notice_shown(self) -> bool:
        return self._get("app/tray_notice_shown", False, bool)
    
    @tray_notice_shown.setter
    def tray_notice_shown(self, value: bool) -> None:
        self._set("app/tray_notice_shown", value)
    
    # --- プレビュー ---
    @property
    def converter(self) -> Optional[str]:
        value = self._s.value("preview/converter")
        return str(value) if value else None
    
    @converter.setter
    def converter(self, value: str) -> None:
        self._set("preview/converter", value)
    
    @property
    def libreoffice_path(self) -> Optional[str]:
        value = self._s.value("preview/libreoffice_path")
        return None if value is None else str(value)
    
    @libreoffice_path.setter
    def libreoffice_path(self, value: str) -> None:
        self._set("preview/libreoffice_path", value)
    
    @property
    def preview_zoom(self) -> int:
        return self._get("preview/zoom", 100, int)
    
    @preview_zoom.setter
    def preview_zoom(self, value: int) -> None:
        self._set("preview/zoom", int(value))
    
    # --- ウィンドウ ---
    def save_bytes(self, key: str, data) -> None:
        self._set(f"window/{key}", data)
    
    def load_bytes(self, key: str):
        return self._s.value(f"window/{key}")
    
    def sync(self) -> None:
        self._s.sync()


def _push(items: list[str], value: str) -> list[str]:
    value = value.strip()
    if not value:
        return items
    items = [v for v in items if v != value]
    items.insert(0, value)
    return items[:MAX_HISTORY]


def apply_to_config(settings: UserSettings) -> None:
    """画面で変更された値を、実行中の設定（Config）に反映する"""
    from src.common.config import get_config
    
    config = get_config()
    if (limit := settings.match_limit) is not None:
        config.search_max_matches_per_file = limit
    if (workers := settings.workers) is not None:
        config.search_workers = workers
    if converter := settings.converter:
        config.office_converter = converter
    if (path := settings.libreoffice_path) is not None:
        config.libreoffice_path = path


def limit_label(value: int) -> str:
    return "無制限" if value <= 0 else f"{value:,} 件"
