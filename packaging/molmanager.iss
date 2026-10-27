; MolManager Windows setup.
; Build the PyInstaller folder first, from the repo root:
;   pyinstaller packaging/molmanager.spec
; Then:
;   ISCC packaging/molmanager.iss
; Silent install (no wizard, no launch):
;   dist\installer\MolManager-<version>-setup.exe /VERYSILENT /NORESTART
;
; AppId stays constant across upgrades. AppVersion should match molmanager.__version__.
; Pass /DAppVersion=x.y.z from ISCC when the version changes.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef SourceDir
  #define SourceDir "dist\MolManager"
#endif

[Setup]
AppId={{8F4C2A1E-7B63-4D90-9E15-2C6A8B0D4F71}
AppName=MolManager
AppVersion={#AppVersion}
AppPublisher=Hunter Picard
DefaultDirName={localappdata}\MolManager
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir=dist\installer
OutputBaseFilename=MolManager-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\MolManager.exe
CloseApplications=yes

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\MolManager"; Filename: "{app}\MolManager.exe"

[Run]
Filename: "{app}\MolManager.exe"; Description: "Launch MolManager"; Flags: nowait postinstall skipifsilent
