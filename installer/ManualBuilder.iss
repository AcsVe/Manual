; Inno Setup script — ManualBuilderSetup.exe
; Build (after PyInstaller):  iscc /DMyAppVersion=1.0.0 installer\ManualBuilder.iss
; - installs to Program Files\ManualBuilder, Start-menu and desktop shortcuts
; - creates the shared data folder %ProgramData%\ManualBuilder writable by every user of the PC
; - an update installs over the old version; the data (database, images, backups, licence) is never touched,
;   also not on uninstall
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "ManualBuilder"
#define MyAppPublisher "AcsVe"
#define MyAppExe "ManualBuilder.exe"

[Setup]
AppId={{8E3A1C74-5B2D-4F6A-A1E9-7C2D4B8F3A61}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=ManualBuilderSetup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
#if FileExists(AddBackslash(CompilerPath) + "Languages\Arabic.isl")
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Dirs]
Name: "{commonappdata}\ManualBuilder"; Permissions: users-modify
Name: "{commonappdata}\ManualBuilder\backups"; Permissions: users-modify

[Files]
Source: "..\dist\ManualBuilder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
