; Script generated for Inno Setup Compiler 6.x
; DeskPilot — Multi-Agent Windows Desktop Assistant
; AWS "Agents for Humans" Hackathon Submission

#define MyAppName "DeskPilot"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "AWS Hackathon Team — DeskPilot"
#define MyAppURL "https://github.com/aws-samples/agents-for-humans"
#define MyAppExeName "DeskPilot.exe"

[Setup]
; App Identity & Version
AppId={{C38A12B9-75E2-4C10-9118-E8102A1F935E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Installation Paths
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes

; Output Configuration
OutputDir=..\dist\installer
OutputBaseFilename=DeskPilot-Setup-v{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; Compression & Packaging
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Distribute all files produced by PyInstaller --onedir build
Source: "..\dist\DeskPilot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
