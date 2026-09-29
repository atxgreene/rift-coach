; Macro Goblin installer (Inno Setup 6).
;   ISCC.exe /DMyAppVersion=1.1.0 packaging\installer.iss
; Per-user install: no admin prompt, installs to %LOCALAPPDATA%\Programs\Macro Goblin.
; User data (settings, match notes, recordings) lives in %LOCALAPPDATA%\MacroGoblin and is kept on uninstall.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "Macro Goblin"
#define MyAppExe "MacroGoblin.exe"
#define MyAppUrl "https://github.com/atxgreene/rift-coach"

[Setup]
AppId={{6A1E5F7C-3B2D-4C8E-9F10-4D6B7A2C9E31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=ATXGreene
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}/blob/main/docs/TROUBLESHOOTING.md
AppUpdatesURL={#MyAppUrl}/releases/latest
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoDescription={#MyAppName} Setup
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=MacroGoblin-Setup
SetupIconFile=..\assets\app-icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
WizardStyle=modern
WizardImageFile=wizard-large-100.bmp,wizard-large-125.bmp,wizard-large-150.bmp,wizard-large-200.bmp
WizardSmallImageFile=wizard-small-100.bmp,wizard-small-125.bmp,wizard-small-150.bmp,wizard-small-200.bmp
Compression=lzma2/ultra64
SolidCompression=yes
AppMutex=MacroGoblinSingleInstance
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nMacro Goblin is a read-only coach: it uses Riot's official local game API and never touches the League client.

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start Macro Goblin when Windows starts (opens minimized)"; GroupDescription: "Options:"; Flags: unchecked

[Files]
Source: "..\dist\MacroGoblin\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Comment: "Live macro coach for League of Legends"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; Same value the app's "Start with Windows" switch writes, so the two stay in sync.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "MacroGoblin"; ValueData: """{app}\{#MyAppExe}"" --minimized"; Tasks: startup; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "MacroGoblin"; Flags: dontcreatekey uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall; Check: ShouldLaunch

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function ShouldLaunch: Boolean;
var
  I: Integer;
begin
  Result := True;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/NOLAUNCH') = 0 then
      Result := False;
end;
