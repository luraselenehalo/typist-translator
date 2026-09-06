; Typist Translator - Windows installer
;
; Compiled by build.py, which substitutes the /D values below from about.py so
; the version never has to be typed in two places.
;
; Two requirements shape this file:
;
;   * The FIRST page picks the interface language, from the same four the app
;     itself offers. ShowLanguageDialog does that, and Inno ships professional
;     translations for all four, so the wizard is fully localised - not just
;     our own strings.
;   * The task checkboxes are the LAST thing before installing. By default Inno
;     puts Tasks third from last (Tasks -> Ready -> Finished), so the Ready
;     summary page is disabled.
;
; The install is PER-USER, into %LOCALAPPDATA%\Programs. That is what lets the
; app update itself: no UAC prompt on install, and none on any update either,
; because the program directory belongs to the user who runs it. It also means
; HKCU\...\Run is the correct place for "start with Windows", and that
; {userappdata} resolves to the real user rather than to an elevating admin.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\TypistTranslator"
#endif
#ifndef OutputDir
  #define OutputDir "..\release"
#endif
#ifndef AssetsDir
  #define AssetsDir "."
#endif

#define AppName        "Typist Translator"
#define AppPublisher   "Mrgunshi"
#define AppUrl         "https://github.com/luraselenehalo/typist-translator"
#define AppExe         "TypistTranslator.exe"

[Setup]
; Never change AppId. It is the upgrade identity: a different one makes every
; future release install a second copy beside this one and leaves two entries
; in Add/Remove Programs.
AppId={{D5A42794-BC5C-4F17-B905-BAE69A6255EB}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={localappdata}\Programs\TypistTranslator
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; The task checkboxes have to be the last page, so the Ready summary goes.
DisableReadyPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=TypistTranslator-Setup-{#AppVersion}
SetupIconFile={#AssetsDir}\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=yes
CloseApplications=no
RestartApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "th"; MessagesFile: "compiler:Languages\Thai.isl"
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "zh"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[CustomMessages]
en.LaunchApp=Launch %1
en.AutoStart=Start %1 when Windows starts
en.WaitingForApp=Waiting for the running copy to close...
th.LaunchApp=เปิด %1
th.AutoStart=เปิด %1 พร้อม Windows
th.WaitingForApp=กำลังรอให้โปรแกรมที่เปิดอยู่ปิดตัวลง...
ja.LaunchApp=%1 を起動する
ja.AutoStart=Windows の起動時に %1 を起動する
ja.WaitingForApp=起動中のコピーが終了するのを待っています...
zh.LaunchApp=启动 %1
zh.AutoStart=开机时自动启动 %1
zh.WaitingForApp=正在等待运行中的程序关闭...

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "{cm:AutoStart,{#AppName}}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
; Check: instead of Tasks: so that a silent update repeats whatever the user
; chose the first time. During an interactive run the Check reads the checkbox;
; during a silent one it reads what was recorded at the previous install.
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Check: WantsDesktopIcon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "TypistTranslator"; \
  ValueData: """{app}\{#AppExe}"""; Flags: uninsdeletevalue; Check: WantsAutoStart
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: none; ValueName: "TypistTranslator"; \
  Flags: deletevalue uninsdeletevalue; Check: NoAutoStart

; Remembered so a silent update does not quietly undo the user's choices, and so
; the app can show them in its own Settings tab.
Root: HKCU; Subkey: "Software\TypistTranslator"; ValueType: string; \
  ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\TypistTranslator"; ValueType: string; \
  ValueName: "Version"; ValueData: "{#AppVersion}"
Root: HKCU; Subkey: "Software\TypistTranslator"; ValueType: string; \
  ValueName: "Language"; ValueData: "{language}"
Root: HKCU; Subkey: "Software\TypistTranslator"; ValueType: dword; \
  ValueName: "DesktopIcon"; ValueData: "{code:DesktopIconValue}"
Root: HKCU; Subkey: "Software\TypistTranslator"; ValueType: dword; \
  ValueName: "AutoStart"; ValueData: "{code:AutoStartValue}"

[Run]
; Interactive: the ordinary "run it now" tick box on the finished page.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp,{#AppName}}"; \
  Flags: nowait postinstall skipifsilent runasoriginaluser
; Silent update: bring the app back afterwards. Deliberately WITHOUT
; skipifsilent - that flag would skip this entry in exactly the mode the
; auto-updater uses, and the app would vanish instead of restarting.
Filename: "{app}\{#AppExe}"; Parameters: "--updated"; \
  Flags: nowait runasoriginaluser; Check: WantsRelaunch

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"

[Code]
const
  AppMutex = 'TypistTranslator.SingleInstance.v1';
  OptionsKey = 'Software\TypistTranslator';

{ True when this run was told to relaunch the app - the auto-update path. }
function WantsRelaunch: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

{ Whether an optional extra should be installed.

  Three cases, and all three have to be right:

    interactive  - the wizard checkbox wins, even on a re-install, because the
                   user is looking at it and just answered the question.
    silent update - what the user chose last time wins. A self-update must not
                   quietly add a desktop icon they removed, or drop one they
                   wanted.
    silent first install - nothing is recorded yet, so honour /TASKS from the
                   command line, which is what WizardIsTaskSelected reflects. }
function OptionOrTask(ValueName, TaskName: String): Boolean;
var
  Recorded: Cardinal;
begin
  if WizardSilent and
     RegQueryDWordValue(HKEY_CURRENT_USER, OptionsKey, ValueName, Recorded) then
    Result := Recorded <> 0
  else
    Result := WizardIsTaskSelected(TaskName);
end;

function WantsDesktopIcon: Boolean;
begin
  Result := OptionOrTask('DesktopIcon', 'desktopicon');
end;

function WantsAutoStart: Boolean;
begin
  Result := OptionOrTask('AutoStart', 'autostart');
end;

{ Check: names a function, it does not take an expression, so the negative
  case needs its own. Unticking "start with Windows" has to actively remove the
  Run value, otherwise a previous install's entry would survive forever. }
function NoAutoStart: Boolean;
begin
  Result := not WantsAutoStart;
end;

{ Scripted constants receive a string argument and return a string; these feed
  the two DWORD registry values that remember the choices for silent updates. }
function DesktopIconValue(Param: String): String;
begin
  if WantsDesktopIcon then Result := '1' else Result := '0';
end;

function AutoStartValue(Param: String): String;
begin
  if WantsAutoStart then Result := '1' else Result := '0';
end;

{ Never copy over a running copy.

  The app holds its own executable and every loaded DLL open, so the copy would
  simply fail partway and leave a mixed old/new tree. Waiting on the same named
  mutex the app itself takes is exact: it is released the moment the process
  dies, however it dies. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Waited: Integer;
begin
  Result := '';
  Waited := 0;
  while CheckForMutexes(AppMutex) and (Waited < 30000) do
  begin
    if Waited = 0 then
      WizardForm.StatusLabel.Caption := ExpandConstant('{cm:WaitingForApp}');
    Sleep(500);
    Waited := Waited + 500;
  end;
  if CheckForMutexes(AppMutex) then
    Result := 'Typist Translator is still running. Please close it (right-click' +
              ' its tray icon and choose Exit) and run this installer again.';
end;
