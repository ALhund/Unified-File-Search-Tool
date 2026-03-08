"""設定管理モジュール。

XML ベースの設定ファイルを読み込み、アプリケーション全体で利用する。
ポータブル運用を優先し、書き込み不可の場合は %LOCALAPPDATA% へフォールバックする。

注意: このモジュールはロガーより先にロードされるため、
      警告の出力には ``sys.stderr`` を使用している（循環依存の回避）。
"""

import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RegexOptions:
    """正規表現のデフォルトオプション設定。"""

    ignore_case: bool = True
    """大文字小文字を無視するか。"""

    multiline: bool = False
    """マルチラインモード（^ と $ が各行にマッチ）を有効にするか。"""

    dot_matches_newline: bool = False
    """ドットが改行にもマッチするか（DOTALL モード）。"""


@dataclass
class SearchDefaults:
    """検索のデフォルト動作設定。"""

    case_sensitive: bool = False
    """大文字小文字を区別するか。"""

    use_regex: bool = False
    """正規表現モードをデフォルトで有効にするか。"""

    match_whole: bool = False
    """全文一致（ブロック全体がクエリと一致）をデフォルトにするか。"""

    include_subfolders: bool = True
    """サブフォルダを検索対象に含めるか。"""


@dataclass
class Config:
    """アプリケーション全体の設定。

    :meth:`load` クラスメソッドで XML から読み込む。
    シングルトンとして利用する場合は :func:`get_config` を使用する。
    """

    large_file_warning_threshold_mb: int = 20
    """この MB 数を超えるファイルを処理する前に警告を表示する閾値。"""

    search_max_matches_per_file: int = 50
    """1 ファイルあたりのマッチ件数の上限。超えた場合は打ち切り扱い。"""

    search_parallel_workers: int = 4
    """並列検索に使用するワーカースレッド数。"""

    logs_max_lines_per_file: int = 1000
    """ログファイル 1 本あたりの最大行数（FIFO ローテーション）。"""

    logging_level: str = "Information"
    """最小ログレベル文字列（"Debug" / "Information" / "Warning" / "Critical"）。"""

    target_extensions: list[str] = field(default_factory=lambda: [
        "pptx", "xlsx", "docx", "pdf", "md", "txt", "log"
    ])
    """検索対象とするファイル拡張子一覧（ドットなし小文字）。"""

    search_defaults: SearchDefaults = field(default_factory=SearchDefaults)
    """検索画面の初期値設定。"""

    regex_options: RegexOptions = field(default_factory=RegexOptions)
    """正規表現モードの初期オプション設定。"""

    _config_path: Path | None = field(default=None, repr=False)
    _logs_path: Path | None = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # クラスメソッド: パス解決
    # ------------------------------------------------------------------

    @classmethod
    def get_app_name(cls) -> str:
        """アプリケーション名を返す。"""
        return "Unified-File-Search-Tool"

    @classmethod
    def get_portable_base(cls) -> Path:
        """実行ファイルと同じディレクトリを返す。

        exe 化時は実行ファイルの親ディレクトリ、
        開発実行時はカレントディレクトリを返す。
        """
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent
        return Path.cwd()

    @classmethod
    def get_user_base(cls) -> Path:
        """ユーザー領域のベースパスを返す。

        %LOCALAPPDATA% が存在すればその下、なければホームディレクトリを使用する。
        """
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            return Path(local_app_data) / cls.get_app_name()
        return Path.home() / ".unified-file-search-tool"

    @classmethod
    def resolve_config_path(cls) -> Path:
        """設定ファイルのパスを解決する（ポータブルパス優先）。

        存在するパスを返す。どちらも存在しない場合はポータブルパスへの
        書き込みを試み、失敗時はユーザーパスを返す。
        """
        portable_path = cls.get_portable_base() / "Config" / "config.xml"
        if portable_path.exists():
            return portable_path

        user_path = cls.get_user_base() / "Config" / "config.xml"
        if user_path.exists():
            return user_path

        try:
            portable_path.parent.mkdir(parents=True, exist_ok=True)
            return portable_path
        except (PermissionError, OSError):
            user_path.parent.mkdir(parents=True, exist_ok=True)
            return user_path

    @classmethod
    def resolve_logs_path(cls) -> Path:
        """ログ出力ディレクトリのパスを解決する（ポータブルパス優先）。

        書き込みテストに失敗した場合はユーザーパスにフォールバックする。
        """
        portable_path = cls.get_portable_base() / "logs"
        try:
            portable_path.mkdir(parents=True, exist_ok=True)
            test_file = portable_path / ".write_test"
            test_file.touch()
            test_file.unlink()
            return portable_path
        except (PermissionError, OSError):
            user_path = cls.get_user_base() / "logs"
            user_path.mkdir(parents=True, exist_ok=True)
            return user_path

    # ------------------------------------------------------------------
    # クラスメソッド: ロード
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, config_path: Path | None = None) -> "Config":
        """設定ファイルを読み込んで Config インスタンスを返す。

        Args:
            config_path: 読み込む XML ファイルのパス。
                         ``None`` の場合は :meth:`resolve_config_path` で自動解決する。

        Returns:
            読み込んだ設定。ファイルが存在しない場合はデフォルト値を返す。
        """
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
            cls._apply_xml(config, root)
        except (ET.ParseError, ValueError) as exc:
            # ロガーより先にロードされるため sys.stderr を直接使用する
            print(
                f"Warning: Failed to parse config file: {exc}",
                file=sys.stderr,
            )

        return config

    @classmethod
    def _apply_xml(cls, config: "Config", root: ET.Element) -> None:
        """XML ルート要素を Config インスタンスに反映する（内部ヘルパー）。

        DRY 原則のため、XML パース処理をこのメソッドに集約する。

        Args:
            config: 更新対象の Config インスタンス。
            root: パース済み XML のルート要素。
        """
        def text_of(tag: str, default: str) -> str:
            """指定タグのテキストを返す。存在しなければ default を返す。"""
            elem = root.find(tag)
            return (elem.text or default) if elem is not None else default

        config.large_file_warning_threshold_mb = int(
            text_of("large_file_warning_threshold_mb", "20")
        )
        config.search_max_matches_per_file = int(
            text_of("search_max_matches_per_file", "50")
        )
        config.search_parallel_workers = int(
            text_of("search_parallel_workers", "4")
        )
        config.logs_max_lines_per_file = int(
            text_of("logs_max_lines_per_file", "1000")
        )
        config.logging_level = text_of("logging_level", "Information")

        # 対象拡張子
        ext_elem = root.find("target_extensions")
        if ext_elem is not None:
            extensions = [
                ext.text.strip().lower()
                for ext in ext_elem.findall("ext")
                if ext.text
            ]
            if extensions:
                config.target_extensions = extensions

        # 検索デフォルト
        search_elem = root.find("search_defaults")
        if search_elem is not None:
            cls._apply_search_defaults(config.search_defaults, search_elem)

        # 正規表現オプション
        regex_elem = root.find("regex_options")
        if regex_elem is not None:
            cls._apply_regex_options(config.regex_options, regex_elem)

    @classmethod
    def _apply_search_defaults(
        cls,
        defaults: SearchDefaults,
        elem: ET.Element,
    ) -> None:
        """search_defaults XML 要素を SearchDefaults に反映する（内部ヘルパー）。

        Args:
            defaults: 更新対象の SearchDefaults インスタンス。
            elem: ``<search_defaults>`` XML 要素。
        """
        def bool_of(tag: str) -> bool | None:
            """指定タグの値を bool に変換する。タグが無ければ None を返す。"""
            child = elem.find(tag)
            return (child.text == "true") if child is not None else None

        if (val := bool_of("case_sensitive")) is not None:
            defaults.case_sensitive = val
        if (val := bool_of("use_regex")) is not None:
            defaults.use_regex = val
        if (val := bool_of("match_whole")) is not None:
            defaults.match_whole = val
        if (val := bool_of("include_subfolders")) is not None:
            defaults.include_subfolders = val

    @classmethod
    def _apply_regex_options(
        cls,
        options: RegexOptions,
        elem: ET.Element,
    ) -> None:
        """regex_options XML 要素を RegexOptions に反映する（内部ヘルパー）。

        Args:
            options: 更新対象の RegexOptions インスタンス。
            elem: ``<regex_options>`` XML 要素。
        """
        def bool_of(tag: str) -> bool | None:
            """指定タグの値を bool に変換する。タグが無ければ None を返す。"""
            child = elem.find(tag)
            return (child.text == "true") if child is not None else None

        if (val := bool_of("ignore_case")) is not None:
            options.ignore_case = val
        if (val := bool_of("multiline")) is not None:
            options.multiline = val
        if (val := bool_of("dot_matches_newline")) is not None:
            options.dot_matches_newline = val

    # ------------------------------------------------------------------
    # プロパティ
    # ------------------------------------------------------------------

    @property
    def config_path(self) -> Path:
        """設定ファイルのパス（遅延解決）。"""
        if self._config_path is None:
            self._config_path = self.resolve_config_path()
        return self._config_path

    @property
    def logs_path(self) -> Path:
        """ログ出力ディレクトリのパス（遅延解決）。"""
        if self._logs_path is None:
            self._logs_path = self.resolve_logs_path()
        return self._logs_path

    @property
    def large_file_warning_threshold_bytes(self) -> int:
        """:attr:`large_file_warning_threshold_mb` をバイト単位に変換した値。"""
        return self.large_file_warning_threshold_mb * 1024 * 1024


# ---------------------------------------------------------------------------
# シングルトン管理
# ---------------------------------------------------------------------------

_config_instance: Config | None = None


def get_config() -> Config:
    """設定のシングルトンインスタンスを取得する。

    初回呼び出し時に :meth:`Config.load` を実行する。

    Returns:
        全アプリケーションで共有する Config インスタンス。
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = Config.load()
    return _config_instance


def reload_config() -> Config:
    """設定を再読み込みしてシングルトンを更新する。

    Returns:
        新しく読み込まれた Config インスタンス。
    """
    global _config_instance
    _config_instance = Config.load()
    return _config_instance
