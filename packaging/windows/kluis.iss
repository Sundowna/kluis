; Inno Setup script for Kluis on Windows 10/11. Built by packaging/windows/build.sh:
;   ISCC /DVersion=1.2.0 /DSourceDir=dist\Kluis /DOutputDir=dist packaging\windows\kluis.iss
; Installs for the current user only (no administrator rights), like the Linux packages install for the system.
; Uninstalling keeps your settings in %LOCALAPPDATA%\Kluis and never touches your files or Proton Drive.

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\Kluis"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif

[Setup]
AppId={{8350A861-7109-46BF-8B1B-38B3A4F29093}
AppName=Kluis
AppVersion={#Version}
AppVerName=Kluis {#Version}
AppPublisher=Kluis (unofficial Proton Drive client)
AppPublisherURL=https://github.com/Sundowna/kluis
AppSupportURL=https://github.com/Sundowna/kluis/issues
AppUpdatesURL=https://github.com/Sundowna/kluis/releases
AppComments=Unofficial Proton Drive client. Not affiliated with Proton AG.
DefaultDirName={localappdata}\Programs\Kluis
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=Kluis-Setup-{#Version}
SetupIconFile=kluis.ico
UninstallDisplayIcon={app}\Kluis.exe
UninstallDisplayName=Kluis
LicenseFile=..\..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
VersionInfoVersion={#Version}
VersionInfoProductName=Kluis

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; an update replaces the whole program folder, so no file of an older Kluis stays behind
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{userprograms}\Kluis"; Filename: "{app}\Kluis.exe"; Comment: "Proton Drive sync (unofficial)"
Name: "{userdesktop}\Kluis"; Filename: "{app}\Kluis.exe"; Tasks: desktopicon

[Registry]
; Kluis writes this value itself (Settings → Start at sign-in); uninstalling removes it
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Kluis"; Flags: dontcreatekey uninsdeletevalue

[Run]
Filename: "{app}\Kluis.exe"; Description: "Start Kluis"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/im Kluis.exe /f"; Flags: runhidden; RunOnceId: "StopKluis"
