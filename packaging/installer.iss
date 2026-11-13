; Unified File Search のインストーラー（Inno Setup 6）
; 使い方: packaging\build.py で dist\UnifiedFileSearch を作ってから
;   ISCC.exe /DAppVersion=0.3.0 packaging\installer.iss

#define AppName "Unified File Search"
#define AppExe "UnifiedFileSearch.exe"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8F3C2A51-6B7D-4E2A-9C1E-5A7B3D2F9E10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\UnifiedFileSearch
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; 管理者権限なしで、利用者ごとにインストールできる（必要ならすべてのユーザー向けも選べる）
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=UnifiedFileSearch-{#AppVersion}-setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\UnifiedFileSearch\*"; DestDir: "{app}"; Excludes: "Config\*,logs\*,cache\*"; Flags: ignoreversion recursesubdirs createallsubdirs
; 設定ファイルは、更新インストールで利用者の変更を上書きしない
Source: "..\dist\UnifiedFileSearch\Config\*"; DestDir: "{app}\Config"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\cache"
