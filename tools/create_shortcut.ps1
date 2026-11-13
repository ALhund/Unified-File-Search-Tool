# デスクトップとスタートメニューにアイコン付きのショートカットを作る
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$main = Join-Path $root "main.py"
$icon = Join-Path $root "assets\app.ico"
$shell = New-Object -ComObject WScript.Shell

$targets = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "")
)
foreach ($folder in $targets) {
    $path = Join-Path $folder "Unified File Search.lnk"
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $pythonw
    $link.Arguments = "`"$main`""
    $link.WorkingDirectory = $root
    $link.IconLocation = "$icon,0"
    $link.Description = "Office・PDF・テキストをまとめて検索"
    $link.Save()
    Write-Host "作成しました: $path"
}
