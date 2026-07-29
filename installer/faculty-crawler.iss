#define AppName "高校教师信息采集工具"
#define AppPublisher "FacultyCrawler"
#define AppExeName "FacultyCrawler.exe"

#ifndef AppVersion
  #error AppVersion must be supplied by build_installer.ps1
#endif
#ifndef ApplicationRoot
  #error ApplicationRoot must be supplied by build_installer.ps1
#endif

[Setup]
AppId={{49E35E7A-8471-4D11-A4B2-337E9F68E426}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}.0
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\FacultyCrawler
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=FacultyCrawler-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
Uninstallable=yes
InfoAfterFile=..\使用说明.txt

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "{#ApplicationRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeUninstall(): Boolean;
begin
  MsgBox('卸载只删除已安装的程序文件。导出的 Excel 和本地应用数据会保留，便于以后继续使用或手动备份。', mbInformation, MB_OK);
  Result := True;
end;
