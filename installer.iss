; HASS.agent-mic-state-plugin Installer
; Built with Inno Setup 6.x
; https://jrsoftware.org/isinfo.php

#define MyAppName "HASS.agent-mic-state-plugin"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "HASS.agent-mic-state-plugin"
#define MyAppURL "https://github.com/SkillfulHacking/HASS.agent-mic-state-plugin"
#define MyAppExeName "discord_voice_state.exe"
#define MyOutputDir "installer_output"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\HASS.agent-mic-state-plugin
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir={#MyOutputDir}
OutputBaseFilename=HASS.agent-mic-state-plugin-setup-v{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
; No elevation required — installs to Program Files but no services
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Main executable built by PyInstaller
Source: "..\dist\discord_voice_state.exe"; DestDir: "{app}"; Flags: ignoreversion

; Documentation
Source: "..\README.md";           DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE";             DestDir: "{app}"; Flags: ignoreversion
Source: "..\PRIVACY_POLICY.md";   DestDir: "{app}"; Flags: ignoreversion
Source: "..\TERMS_OF_SERVICE.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Registry]
; Store install path so HASS.Agent sensor script can find the exe
Root: HKLM; Subkey: "SOFTWARE\HASS.agent-mic-state-plugin"; \
  ValueType: string; ValueName: "InstallPath"; \
  ValueData: "{app}\{#MyAppExeName}"; Flags: createvalueifdoesntexist

[UninstallDelete]
; Clean up log files on uninstall
Type: filesandordirs; Name: "{userappdata}\hass-mic-state"

[Code]
// Optional: show install path after setup completes
procedure CurStepChanged(CurStep: TSetupStep);
var
  ExePath: String;
begin
  if CurStep = ssDone then
  begin
    ExePath := ExpandConstant('{app}\{#MyAppExeName}');
    MsgBox(
      'Installation complete!' + #13#10 + #13#10 +
      'Add this sensor to HASS.Agent:' + #13#10 + #13#10 +
      'Type: PowerShell Sensor' + #13#10 +
      'Command: & "' + ExePath + '"' + #13#10 + #13#10 +
      'This path has been copied to your clipboard.',
      mbInformation, MB_OK
    );
    Clipboard().AsText := '& "' + ExePath + '"';
  end;
end;
