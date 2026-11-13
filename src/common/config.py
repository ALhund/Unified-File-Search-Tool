"""設定管理モジュール

XMLベースの設定ファイルを読み込み、アプリケーション全体で利用する。
ポータブル運用を優先し、書き込み不可の場合は%LOCALAPPDATA%へフォールバック。
"""

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RegexOptions:
    """正規表現オプション"""
    ignore_case: bool = True
    multiline: bool = False
    dot_matches_newline: bool = False


@dataclass
class SearchDefaults:
    """検索のデフォルト設定"""
    case_sensitive: bool = False
    use_regex: bool = False
    match_whole: bool = False
    include_subfolders: bool = True


@dataclass
class Config:
    """アプリケーション設定"""
    
    large_file_warning_threshold_mb: int = 20
    search_max_matches_per_file: int = 1000  # 0 = 無制限
    logs_max_lines_per_file: int = 1000
    logging_level: str = "Information"
    target_extensions: list[str] = field(default_factory=lambda: [
        "pptx", "ppt", "xlsx", "xlsm", "xls", "docx", "doc", "pdf", "md", "txt", "log"
    ])
    search_defaults: SearchDefaults = field(default_factory=SearchDefaults)
    regex_options: RegexOptions = field(default_factory=RegexOptions)
    
    # 検索の並列数（0 = CPU数から自動）
    search_workers: int = 0
    # 抽出結果キャッシュ（2回目以降の検索を高速化）
    extraction_cache_enabled: bool = True
    cache_max_size_mb: int = 500
    # Office→PDF変換: auto / msoffice / libreoffice / none
    office_converter: str = "auto"
    libreoffice_path: str = ""
    preview_conversion_timeout_sec: int = 120
    preview_max_hits: int = 1000
    
    _config_path: Optional[Path] = field(default=None, repr=False)
    _logs_path: Optional[Path] = field(default=None, repr=False)
    _cache_path: Optional[Path] = field(default=None, repr=False)
    
    @classmethod
    def get_app_name(cls) -> str:
        return "Unified-File-Search-Tool"
    
    @classmethod
    def get_portable_base(cls) -> Path:
        """実行ファイルと同じフォルダを取得"""
        # 開発時はリポジトリのフォルダ、exe化時は実行ファイルの場所
        from src.common.paths import app_dir
        return app_dir()
    
    @classmethod
    def get_user_base(cls) -> Path:
        """ユーザー領域のベースパスを取得"""
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            return Path(local_app_data) / cls.get_app_name()
        # フォールバック
        return Path.home() / ".unified-file-search-tool"
    
    @classmethod
    def resolve_config_path(cls) -> Path:
        """設定ファイルのパスを解決（ポータブル優先）"""
        portable_path = cls.get_portable_base() / "Config" / "config.xml"
        if portable_path.exists():
            return portable_path
        
        user_path = cls.get_user_base() / "Config" / "config.xml"
        if user_path.exists():
            return user_path
        
        # 新規作成用のパス（書き込み可能かテスト）
        try:
            portable_path.parent.mkdir(parents=True, exist_ok=True)
            return portable_path
        except (PermissionError, OSError):
            user_path.parent.mkdir(parents=True, exist_ok=True)
            return user_path
    
    @classmethod
    def _resolve_writable_dir(cls, name: str) -> Path:
        """書き込み可能なフォルダを解決（ポータブル優先）"""
        portable_path = cls.get_portable_base() / name
        try:
            portable_path.mkdir(parents=True, exist_ok=True)
            # 書き込みテスト
            test_file = portable_path / f".write_test_{os.getpid()}"
            test_file.touch()
            test_file.unlink()
            return portable_path
        except (PermissionError, OSError):
            user_path = cls.get_user_base() / name
            user_path.mkdir(parents=True, exist_ok=True)
            return user_path
    
    @classmethod
    def resolve_logs_path(cls) -> Path:
        """ログフォルダのパスを解決（ポータブル優先）"""
        return cls._resolve_writable_dir("logs")
    
    @classmethod
    def resolve_cache_path(cls) -> Path:
        """キャッシュフォルダのパスを解決（ポータブル優先）"""
        return cls._resolve_writable_dir("cache")
    
    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "Config":
        """設定ファイルを読み込む"""
        if config_path is None:
            config_path = cls.resolve_config_path()
        
        config = cls()
        config._config_path = config_path
        config._logs_path = cls.resolve_logs_path()
        
        if not config_path.exists():
            return config
        
        try:
            tree = ET.parse(config_path)
            root = tree.getroot()
            
            # 基本設定
            if (elem := root.find("large_file_warning_threshold_mb")) is not None:
                config.large_file_warning_threshold_mb = int(elem.text or "20")
            
            if (elem := root.find("search_max_matches_per_file")) is not None:
                config.search_max_matches_per_file = int(elem.text or "1000")
            
            if (elem := root.find("logs_max_lines_per_file")) is not None:
                config.logs_max_lines_per_file = int(elem.text or "1000")
            
            if (elem := root.find("logging_level")) is not None:
                config.logging_level = elem.text or "Information"
            
            def _int(name: str, default: int) -> int:
                elem = root.find(name)
                return int(elem.text) if elem is not None and elem.text else default
            
            def _text(name: str, default: str) -> str:
                elem = root.find(name)
                return elem.text.strip() if elem is not None and elem.text else default
            
            config.search_workers = _int("search_workers", config.search_workers)
            config.cache_max_size_mb = _int("cache_max_size_mb", config.cache_max_size_mb)
            config.preview_conversion_timeout_sec = _int(
                "preview_conversion_timeout_sec", config.preview_conversion_timeout_sec
            )
            config.preview_max_hits = _int("preview_max_hits", config.preview_max_hits)
            config.extraction_cache_enabled = (
                _text("extraction_cache_enabled", "true").lower() == "true"
            )
            config.office_converter = _text("office_converter", config.office_converter).lower()
            config.libreoffice_path = _text("libreoffice_path", config.libreoffice_path)
            
            # 対象拡張子
            if (ext_elem := root.find("target_extensions")) is not None:
                extensions = []
                for ext in ext_elem.findall("ext"):
                    if ext.text:
                        extensions.append(ext.text.strip().lower().lstrip("."))
                if extensions:
                    config.target_extensions = extensions
            
            # 検索デフォルト
            if (search_elem := root.find("search_defaults")) is not None:
                if (elem := search_elem.find("case_sensitive")) is not None:
                    config.search_defaults.case_sensitive = elem.text == "true"
                if (elem := search_elem.find("use_regex")) is not None:
                    config.search_defaults.use_regex = elem.text == "true"
                if (elem := search_elem.find("match_whole")) is not None:
                    config.search_defaults.match_whole = elem.text == "true"
                if (elem := search_elem.find("include_subfolders")) is not None:
                    config.search_defaults.include_subfolders = elem.text == "true"
            
            # 正規表現オプション
            if (regex_elem := root.find("regex_options")) is not None:
                if (elem := regex_elem.find("ignore_case")) is not None:
                    config.regex_options.ignore_case = elem.text == "true"
                if (elem := regex_elem.find("multiline")) is not None:
                    config.regex_options.multiline = elem.text == "true"
                if (elem := regex_elem.find("dot_matches_newline")) is not None:
                    config.regex_options.dot_matches_newline = elem.text == "true"
        
        except (ET.ParseError, ValueError) as e:
            # パースエラー時はデフォルト値を使用
            print(f"Warning: Failed to parse config file: {e}")
        
        return config
    
    @property
    def config_path(self) -> Path:
        if self._config_path is None:
            self._config_path = self.resolve_config_path()
        return self._config_path
    
    @property
    def logs_path(self) -> Path:
        if self._logs_path is None:
            self._logs_path = self.resolve_logs_path()
        return self._logs_path
    
    @property
    def cache_path(self) -> Path:
        if self._cache_path is None:
            self._cache_path = self.resolve_cache_path()
        return self._cache_path
    
    @property
    def large_file_warning_threshold_bytes(self) -> int:
        return self.large_file_warning_threshold_mb * 1024 * 1024


# シングルトンインスタンス
_config_instance: Optional[Config] = None


def get_config() -> Config:
    """設定のシングルトンインスタンスを取得"""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config.load()
    return _config_instance


def reload_config() -> Config:
    """設定を再読み込み"""
    global _config_instance
    _config_instance = Config.load()
    return _config_instance
