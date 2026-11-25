; Per-user Inno Setup script for Work Memory (no administrator privileges required).

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{8E3F7D2A-4B9E-4A31-9C1B-5F9D2C8A7E11}
AppName=Work Memory
AppVersion={#AppVersion}
AppVerName=Work Memory {#AppVersion}
AppPublisher=Work Memory
DefaultDirName={localappdata}\Programs\WorkMemory
DefaultGroupName=Work Memory
DisableProgramGroupPage=yes
AllowNoIcons=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..
OutputBaseFilename=WorkMemorySetup-{#AppVersion}
SetupIconFile=work_memory.ico
UninstallDisplayIcon={app}\WorkMemory.exe
UninstallDisplayName=Work Memory
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Launch Work Memory silently at Windows startup"; GroupDescription: "Startup options:"

[Files]
Source: "..\dist\WorkMemory\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Work Memory"; Filename: "{app}\WorkMemory.exe"; IconFilename: "{app}\WorkMemory.exe"
Name: "{group}\Uninstall Work Memory"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Work Memory"; Filename: "{app}\WorkMemory.exe"; IconFilename: "{app}\WorkMemory.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "WorkMemory"; ValueData: """{app}\WorkMemory.exe"" --minimized"; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\WorkMemory.exe"; Description: "{cm:LaunchProgram,Work Memory}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // Remove HKCU Run entry even if the user enabled startup later inside app Settings.
  // Never touch %LOCALAPPDATA%\WorkMemory\ so user history, DB, and attachments stay safe.
  if CurUninstallStep = usPostUninstall then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'WorkMemory');
  end;
end;
