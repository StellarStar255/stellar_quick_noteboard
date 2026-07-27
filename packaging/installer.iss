; Inno Setup script for Stellar Quick Noteboard.
; Build from the repo root (after pyinstaller):
;   iscc /DAppVersion=1.0.0 packaging\installer.iss
; To sign, additionally pass:
;   /DSign "/Ssigntool=<signtool command with $f>"

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Stellar Quick Noteboard"
#define AppExeName "StellarQuickNoteboard.exe"

[Setup]
; AppId must never change: it is what makes a newer installer upgrade the
; existing installation in place instead of installing side by side.
AppId={{C7E64B1A-9D34-4F14-A2B7-5E30D1F8C255}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=StellarStar255
AppPublisherURL=https://github.com/StellarStar255/stellar_quick_noteboard
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=StellarQuickNoteboard-{#AppVersion}-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ArchitecturesInstallIn64BitMode=x64compatible
#ifdef Sign
SignTool=signtool
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl")
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\StellarQuickNoteboard\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent
