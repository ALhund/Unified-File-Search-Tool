"""ライセンスコード生成ツール（販売者専用・配布物には含めない）

使い方:
    uv run python tools/license_generator.py            … 画面で操作
    uv run python tools/license_generator.py init       … 鍵を作る（最初の1回だけ）
    uv run python tools/license_generator.py issue --name "山田 太郎" [--memo "ココナラ 取引番号"]
    uv run python tools/license_generator.py verify --name "山田 太郎" --code UFS1-...
    uv run python tools/license_generator.py list

鍵と発行履歴は、既定で ホーム\\UnifiedFileSearch_license\\ に保存する（--key-dir で変更可）。
  private_key.pem      … 秘密鍵。これが漏れると誰でもコードを作れる。リポジトリに入れない・人に渡さない
  issued_licenses.csv  … 発行履歴
鍵を作ると、アプリ側の公開鍵（src/licensing/public_key.py）が書き換わる。
その変更をコミットしてアプリを作り直すと、発行したコードで登録できるようになる。
"""

import argparse
import csv
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.licensing import policy  # noqa: E402
from src.licensing.codec import (  # noqa: E402
    LicenseError,
    generate_private_key,
    issue_code,
    public_key_b64,
    verify_code,
)

DEFAULT_KEY_DIR = Path.home() / "UnifiedFileSearch_license"
PUBLIC_KEY_FILE = ROOT / "src" / "licensing" / "public_key.py"
LEDGER_FIELDS = ["license_id", "name", "edition", "issued", "code", "memo", "created_at"]

BUYER_MESSAGE = """{name} 様

このたびは Unified File Search をご購入いただき、ありがとうございます。
アプリの「ヘルプ（？）→ ライセンスの登録」を開き、次の「登録名」と「ライセンスコード」を
そのままコピーして貼り付けてください。

登録名:
{name}

ライセンスコード:
{code}

※ 登録名とライセンスコードは組み合わせで有効になります。大切に保管してください。
"""


# ---------------------------------------------------------------------------
# 鍵と発行履歴
# ---------------------------------------------------------------------------

class Vault:
    """秘密鍵と発行履歴の保存場所"""
    
    def __init__(self, folder: Path = DEFAULT_KEY_DIR):
        self.folder = Path(folder)
        self.private_key_path = self.folder / "private_key.pem"
        self.ledger_path = self.folder / "issued_licenses.csv"
    
    @property
    def exists(self) -> bool:
        return self.private_key_path.exists()
    
    def create(self, overwrite: bool = False) -> str:
        """鍵を作り、アプリの公開鍵を書き換える。公開鍵（Base64）を返す"""
        from cryptography.hazmat.primitives import serialization
        
        if self.exists and not overwrite:
            raise LicenseError(f"鍵はすでにあります: {self.private_key_path}")
        self._check_outside_repository()
        self.folder.mkdir(parents=True, exist_ok=True)
        key = generate_private_key()
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        self.private_key_path.write_bytes(pem)
        try:
            self.private_key_path.chmod(0o600)
        except OSError:
            pass
        public = public_key_b64(key)
        write_public_key(public)
        return public
    
    def _check_outside_repository(self) -> None:
        try:
            self.folder.resolve().relative_to(ROOT)
        except ValueError:
            return
        raise LicenseError("秘密鍵をリポジトリの中に置くことはできません。別のフォルダを指定してください")
    
    def private_key(self):
        from cryptography.hazmat.primitives import serialization
        
        if not self.exists:
            raise LicenseError("鍵がまだありません。最初に「鍵を作る」を実行してください")
        return serialization.load_pem_private_key(self.private_key_path.read_bytes(), password=None)
    
    def matches_app(self) -> bool:
        """アプリに入っている公開鍵と、この秘密鍵が対応しているか"""
        return public_key_b64(self.private_key()) == read_public_key()
    
    def history(self) -> list[dict]:
        if not self.ledger_path.exists():
            return []
        with open(self.ledger_path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    
    def next_id(self) -> int:
        ids = [int(row["license_id"]) for row in self.history() if row.get("license_id", "").isdigit()]
        return max(ids, default=1000) + 1
    
    def issue(self, name: str, memo: str = "", edition: int = policy.DEFAULT_EDITION) -> dict:
        name = name.strip()
        license_id = self.next_id()
        issued = date.today()
        code = issue_code(self.private_key(), name, license_id, edition, issued)
        row = {
            "license_id": str(license_id),
            "name": name,
            "edition": str(edition),
            "issued": issued.isoformat(),
            "code": code,
            "memo": memo.strip(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        new_file = not self.ledger_path.exists()
        # Excel で開いても文字化けしないよう BOM 付き UTF-8 で書く
        with open(self.ledger_path, "a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
        return row
    
    def verify(self, name: str, code: str):
        return verify_code(self.private_key().public_key(), name, code)


def read_public_key() -> str:
    match = re.search(r'PUBLIC_KEY_B64\s*=\s*"([^"]*)"', PUBLIC_KEY_FILE.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def write_public_key(public: str) -> None:
    text = PUBLIC_KEY_FILE.read_text(encoding="utf-8")
    text = re.sub(r'PUBLIC_KEY_B64\s*=\s*"[^"]*"', f'PUBLIC_KEY_B64 = "{public}"', text)
    PUBLIC_KEY_FILE.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# コマンドライン
# ---------------------------------------------------------------------------

def run_cli(args) -> int:
    vault = Vault(Path(args.key_dir))
    try:
        if args.command == "init":
            public = vault.create(overwrite=args.force)
            print(f"鍵を作りました: {vault.private_key_path}")
            print(f"アプリの公開鍵を書き換えました: {PUBLIC_KEY_FILE}")
            print(f"公開鍵: {public}")
            print("★ 秘密鍵は必ずバックアップしてください（無くすと、新しいコードを発行できなくなります）")
            print("★ src/licensing/public_key.py の変更をコミットして、アプリを作り直してください")
        elif args.command == "issue":
            row = vault.issue(args.name, args.memo or "")
            print(BUYER_MESSAGE.format(name=row["name"], code=row["code"]))
            print(f"（ライセンス番号 {row['license_id']} として {vault.ledger_path} に記録しました）")
        elif args.command == "verify":
            info = vault.verify(args.name, args.code)
            print(f"有効です: {info.name} 様 / No.{info.license_id} / 発行日 {info.issued}")
        elif args.command == "list":
            for row in vault.history():
                print(f"{row['license_id']}\t{row['issued']}\t{row['name']}\t{row.get('memo', '')}")
        return 0
    except LicenseError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------

def run_gui(key_dir: Path) -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import (
        QApplication, QFileDialog, QHBoxLayout, QHeaderView, QLineEdit, QMainWindow,
        QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
        QVBoxLayout, QWidget,
    )
    
    from src.ui.theme import theme
    from src.ui.widgets.common import label, primary_button
    
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    theme().apply(app)
    vault = Vault(key_dir)
    
    window = QMainWindow()
    window.setWindowTitle("Unified File Search — ライセンスコード生成ツール（販売者用）")
    window.resize(820, 640)
    tabs = QTabWidget()
    window.setCentralWidget(tabs)
    
    # --- 発行 ---
    issue_page = QWidget()
    layout = QVBoxLayout(issue_page)
    layout.setContentsMargins(20, 16, 20, 16)
    layout.setSpacing(10)
    layout.addWidget(label("ライセンスコードを発行する", "DialogTitle"))
    status = label("", "Secondary", wrap=True)
    layout.addWidget(status)
    
    layout.addWidget(label("購入者の登録名（アプリに入力してもらう名前）", "SettingsRowTitle"))
    name_edit = QLineEdit()
    name_edit.setPlaceholderText("例: 山田 太郎 / ココナラのユーザー名 など")
    layout.addWidget(name_edit)
    layout.addWidget(label("メモ（任意・発行履歴にだけ残る）", "SettingsRowTitle"))
    memo_edit = QLineEdit()
    memo_edit.setPlaceholderText("例: ココナラ 取引番号 12345")
    layout.addWidget(memo_edit)
    
    issue_button = primary_button("発行する")
    row = QHBoxLayout()
    row.addWidget(issue_button)
    row.addStretch(1)
    layout.addLayout(row)
    
    layout.addWidget(label("購入者に送る文面（そのままコピーして送れます）", "SettingsRowTitle"))
    message = QPlainTextEdit()
    message.setReadOnly(True)
    layout.addWidget(message, 1)
    copy_button = QPushButton("文面をコピー")
    copy_code_button = QPushButton("コードだけコピー")
    row = QHBoxLayout()
    row.addWidget(copy_button)
    row.addWidget(copy_code_button)
    row.addStretch(1)
    layout.addLayout(row)
    tabs.addTab(issue_page, "発行")
    last_code = {"code": ""}
    
    # --- 確認 ---
    verify_page = QWidget()
    v_layout = QVBoxLayout(verify_page)
    v_layout.setContentsMargins(20, 16, 20, 16)
    v_layout.addWidget(label("コードが有効か確かめる（問い合わせ対応用）", "DialogTitle"))
    v_name = QLineEdit()
    v_name.setPlaceholderText("登録名")
    v_code = QPlainTextEdit()
    v_code.setPlaceholderText("UFS1-...")
    v_code.setMaximumHeight(90)
    v_result = label("", "", wrap=True)
    v_button = primary_button("確認する")
    for widget in (v_name, v_code, v_button, v_result):
        v_layout.addWidget(widget)
    v_layout.addStretch(1)
    tabs.addTab(verify_page, "確認")
    
    # --- 発行履歴 ---
    history_page = QWidget()
    h_layout = QVBoxLayout(history_page)
    h_layout.setContentsMargins(20, 16, 20, 16)
    table = QTableWidget(0, 5)
    table.setHorizontalHeaderLabels(["No.", "発行日", "登録名", "メモ", "コード"])
    table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    h_layout.addWidget(table)
    open_folder = QPushButton("保存フォルダを開く")
    h_layout.addWidget(open_folder, 0, Qt.AlignmentFlag.AlignLeft)
    tabs.addTab(history_page, "発行履歴")
    
    # --- 鍵 ---
    key_page = QWidget()
    k_layout = QVBoxLayout(key_page)
    k_layout.setContentsMargins(20, 16, 20, 16)
    k_layout.setSpacing(10)
    k_layout.addWidget(label("署名用の鍵", "DialogTitle"))
    k_info = label("", "Secondary", wrap=True)
    k_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    k_layout.addWidget(k_info)
    k_folder = QPushButton("保存先を変える…")
    k_create = primary_button("鍵を作る（最初の1回だけ）")
    row = QHBoxLayout()
    row.addWidget(k_create)
    row.addWidget(k_folder)
    row.addStretch(1)
    k_layout.addLayout(row)
    k_layout.addWidget(label(
        "・鍵を作ると、アプリ側の公開鍵（src/licensing/public_key.py）が書き換わります。"
        "その変更をコミットしてアプリを作り直すと、ここで発行したコードで登録できるようになります。<br>"
        "・<b>private_key.pem は必ずバックアップ</b>してください。無くすと新しいコードを発行できず、"
        "鍵を作り直すと、それまでに発行したコードはすべて使えなくなります。<br>"
        "・private_key.pem を人に渡したり、リポジトリに入れたりしないでください。",
        "Secondary", wrap=True,
    ))
    k_layout.addStretch(1)
    tabs.addTab(key_page, "鍵の設定")
    
    def refresh() -> None:
        ready = vault.exists
        issue_button.setEnabled(ready)
        v_button.setEnabled(ready)
        k_create.setEnabled(not ready)
        lines = [f"保存先: {vault.folder}"]
        if ready:
            matches = vault.matches_app()
            lines.append("秘密鍵: あり")
            lines.append(
                "アプリの公開鍵: 一致しています" if matches
                else "アプリの公開鍵: 一致していません（別の鍵か、まだ書き換えていません）"
            )
            status.setText(
                f"次のライセンス番号: {vault.next_id()}　|　発行済み: {len(vault.history())} 件"
                + ("" if matches else "　|　⚠ アプリの公開鍵と一致していません（「鍵の設定」を確認）")
            )
        else:
            lines.append("秘密鍵: まだありません")
            status.setText("まだ鍵がありません。「鍵の設定」タブで鍵を作ってください。")
            tabs.setCurrentWidget(key_page)
        k_info.setText("<br>".join(lines))
        history = vault.history()
        table.setRowCount(len(history))
        for r, item in enumerate(reversed(history)):
            for c, key in enumerate(("license_id", "issued", "name", "memo", "code")):
                table.setItem(r, c, QTableWidgetItem(item.get(key, "")))
    
    def do_issue() -> None:
        name = name_edit.text().strip()
        if not name:
            QMessageBox.warning(window, "発行", "購入者の登録名を入力してください。")
            return
        try:
            row = vault.issue(name, memo_edit.text())
        except LicenseError as e:
            QMessageBox.warning(window, "発行", str(e))
            return
        last_code["code"] = row["code"]
        message.setPlainText(BUYER_MESSAGE.format(name=row["name"], code=row["code"]))
        name_edit.clear()
        memo_edit.clear()
        refresh()
    
    def do_verify() -> None:
        try:
            info = vault.verify(v_name.text(), v_code.toPlainText())
            v_result.setText(f"✔ 有効です: {info.name} 様 / No.{info.license_id} / 発行日 {info.issued}")
        except LicenseError as e:
            v_result.setText(f"✖ {e}")
    
    def do_create() -> None:
        answer = QMessageBox.question(
            window, "鍵を作る",
            f"{vault.folder} に鍵を作り、アプリの公開鍵を書き換えます。よろしいですか？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            vault.create()
        except LicenseError as e:
            QMessageBox.warning(window, "鍵を作る", str(e))
            return
        QMessageBox.information(
            window, "鍵を作る",
            "鍵を作りました。\n\n1. private_key.pem をバックアップしてください\n"
            "2. src/licensing/public_key.py の変更をコミットして、アプリを作り直してください",
        )
        refresh()
        tabs.setCurrentWidget(issue_page)
    
    def change_folder() -> None:
        nonlocal vault
        folder = QFileDialog.getExistingDirectory(window, "鍵の保存先", str(vault.folder))
        if folder:
            vault = Vault(Path(folder))
            refresh()
    
    def open_ledger_folder() -> None:
        from src.ui.platform import open_file
        vault.folder.mkdir(parents=True, exist_ok=True)
        open_file(vault.folder)
    
    issue_button.clicked.connect(do_issue)
    name_edit.returnPressed.connect(do_issue)
    copy_button.clicked.connect(lambda: QGuiApplication.clipboard().setText(message.toPlainText()))
    copy_code_button.clicked.connect(lambda: QGuiApplication.clipboard().setText(last_code["code"]))
    v_button.clicked.connect(do_verify)
    k_create.clicked.connect(do_create)
    k_folder.clicked.connect(change_folder)
    open_folder.clicked.connect(open_ledger_folder)
    
    refresh()
    window.show()
    return app.exec()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    
    parser = argparse.ArgumentParser(description="Unified File Search のライセンスコード生成ツール（販売者用）")
    parser.add_argument("--key-dir", default=str(DEFAULT_KEY_DIR), help="鍵と発行履歴の保存先")
    sub = parser.add_subparsers(dest="command")
    init = sub.add_parser("init", help="鍵を作る（最初の1回だけ）")
    init.add_argument("--force", action="store_true", help="既存の鍵を作り直す（発行済みのコードはすべて無効になる）")
    issue = sub.add_parser("issue", help="コードを発行する")
    issue.add_argument("--name", required=True, help="購入者の登録名")
    issue.add_argument("--memo", help="発行履歴に残すメモ")
    verify = sub.add_parser("verify", help="コードを確認する")
    verify.add_argument("--name", required=True)
    verify.add_argument("--code", required=True)
    sub.add_parser("list", help="発行履歴を表示する")
    args = parser.parse_args()
    
    if args.command is None:
        return run_gui(Path(args.key_dir))
    return run_cli(args)


if __name__ == "__main__":
    sys.exit(main())
