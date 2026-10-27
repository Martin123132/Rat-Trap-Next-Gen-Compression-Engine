; UTF-8. Compiled only through build_windows_library_restore_installer.ps1.
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "Sections.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

!define APP_VERSION "5.7.0.10"
!define OWNER "TWO HANDS NETWORK LTD"
!define MARKER "RatTrapDesktopPreview2/v1"
!define ARP "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_KEY}"
!define GMW_PROGID "${APP_KEY}.GMW"
!define RTSF_PROGID "${APP_KEY}.RTSF"

Name "${DISPLAY_NAME}"
OutFile "${OUTPUT_FILE}"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetDatablockOptimize on
SetOverwrite on
AllowSkipFiles off
ShowInstDetails show
ShowUninstDetails show
BrandingText "Two Hands Network Ltd"
Icon "${APP_ICON}"
UninstallIcon "${APP_ICON}"
VIProductVersion "5.7.0.10"
VIAddVersionKey "ProductName" "${DISPLAY_NAME} Setup"
VIAddVersionKey "CompanyName" "${OWNER}"
VIAddVersionKey "FileDescription" "Rat-Trap Desktop Preview 2 Library and project timeline preview"
VIAddVersionKey "FileVersion" "5.7.0.10"
VIAddVersionKey "ProductVersion" "5.7.0.10"
VIAddVersionKey "LegalCopyright" "Copyright 2026 TWO HANDS NETWORK LTD"

!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "Install or update ${DISPLAY_NAME} for your Windows account.$\r$\n$\r$\nThis unsigned Library preview uses the same Desktop Preview 2 installation and shortcuts. Existing archives and recovery keys are kept.$\r$\n$\r$\nOrganise archives, Vaults and backup repositories in a local Library with projects and a timeline. Your stored files stay in their chosen locations. No Python installation or Rat-Trap account is required."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${PAYLOAD_DIR}\Legal\LICENSE.md"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TEXT "${DISPLAY_NAME} is ready. Open it from the existing Start menu folder and choose Library. Create a project and add existing stored items. The five guided lessons remain available.$\r$\n$\r$\nThe app does not update automatically. This Library update installs no new product identity.$\r$\n$\r$\nYour archives and recovery keys remain in the locations you choose."
!insertmacro MUI_PAGE_FINISH
!define MUI_UNCONFIRMPAGE_TEXT_TOP "Remove ${DISPLAY_NAME} from this Windows account? Only files installed by this Setup are removed. Your archives, recovery keys, repositories, local diagnostics, and separate Rat-Trap installations are kept."
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "English"

Var AssociationArgument
Var DesktopArgument
Var ExistingInstallation

; Never traverse directory links during install or uninstall.
!macro CheckDirectory DIRECTORY
  System::Call 'kernel32::GetFileAttributesW(w "${DIRECTORY}") i .r0'
  ${If} $0 != -1
    IntOp $0 $0 & 0x400
    ${If} $0 != 0
      MessageBox MB_OK|MB_ICONSTOP "Setup cannot use a linked installation folder. Choose a normal local Windows profile." /SD IDOK
      SetErrorLevel 3
      Quit
    ${EndIf}
  ${EndIf}
!macroend

!macro CheckBaseDirectories
  !insertmacro CheckDirectory "$LOCALAPPDATA"
  !insertmacro CheckDirectory "$LOCALAPPDATA\Programs"
  !insertmacro CheckDirectory "$LOCALAPPDATA\Programs\Two Hands Network Ltd"
  !insertmacro CheckDirectory "$INSTDIR"
  !include "${CHECK_DIRS_INCLUDE}"
!macroend

; Opening an existing EXE for read/write with no sharing fails while it is
; running or otherwise locked. Never kill a running compression operation.
!macro CheckFileUnlocked FILEPATH
  ${If} ${FileExists} "${FILEPATH}"
    !insertmacro CheckDirectory "${FILEPATH}"
    System::Call 'kernel32::CreateFileW(w "${FILEPATH}", i 0xC0000000, i 0, p 0, i 3, i 0, p 0) p .r0'
    ${If} $0 == -1
      MessageBox MB_OK|MB_ICONSTOP "An installed file is in use or cannot be updated. Close Rat-Trap after its current operation finishes and close any open help files, then try again." /SD IDOK
      SetErrorLevel 4
      Quit
    ${EndIf}
    System::Alloc 52
    Pop $1
    System::Call 'kernel32::GetFileInformationByHandle(p r0, p r1) i .r2'
    ${If} $2 == 0
      System::Free $1
      System::Call 'kernel32::CloseHandle(p r0)'
      SetErrorLevel 3
      Quit
    ${EndIf}
    IntOp $2 $1 + 40
    System::Call '*$2(i .r3)'
    System::Free $1
    System::Call 'kernel32::CloseHandle(p r0)'
    ${If} $3 > 1
      MessageBox MB_OK|MB_ICONSTOP "An installed file is linked to another location. Setup has made no changes." /SD IDOK
      SetErrorLevel 3
      Quit
    ${EndIf}
  ${EndIf}
!macroend

!macro CheckPayloadUnlocked
  !include "${CHECK_FILES_INCLUDE}"
!macroend

!macro CheckWrite
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "Setup could not finish writing the application. Check free space and folder permissions, then run Setup again to repair the installation." /SD IDOK
    SetErrorLevel 5
    Quit
  ${EndIf}
!macroend

!macro RegisterType EXT PROGID LABEL ACTION
  ClearErrors
  WriteRegStr HKCU "Software\Classes\${PROGID}" "" "${LABEL}"
  WriteRegStr HKCU "Software\Classes\${PROGID}\DefaultIcon" "" '$\"$INSTDIR\Rat-Trap-Desktop-Preview-2.exe$\",0'
  WriteRegStr HKCU "Software\Classes\${PROGID}\shell\open\command" "" '$\"$INSTDIR\Rat-Trap-Desktop-Preview-2.exe$\" ${ACTION} $\"%1$\"'
  WriteRegStr HKCU "Software\Classes\${PROGID}\shell\open" "MultiSelectModel" "Single"
  WriteRegBin HKCU "Software\Classes\${EXT}\OpenWithProgids" "${PROGID}" ""
  !insertmacro CheckWrite
!macroend

!macro UnregisterType EXT PROGID ACTION
  ReadRegStr $0 HKCU "Software\Classes\${PROGID}\shell\open\command" ""
  ${If} $0 == '$\"$INSTDIR\Rat-Trap-Desktop-Preview-2.exe$\" ${ACTION} $\"%1$\"'
    DeleteRegValue HKCU "Software\Classes\${EXT}\OpenWithProgids" "${PROGID}"
    DeleteRegKey /ifempty HKCU "Software\Classes\${EXT}\OpenWithProgids"
    DeleteRegKey /ifempty HKCU "Software\Classes\${EXT}"
    DeleteRegKey HKCU "Software\Classes\${PROGID}"
  ${EndIf}
!macroend


Section "Rat-Trap Desktop Preview 2 (required)" Application
  SectionIn RO
  !insertmacro CheckBaseDirectories
  !insertmacro CheckPayloadUnlocked
  !insertmacro CheckFileUnlocked "$INSTDIR\Uninstall.exe"
  ; Record a repairable pending installation before extracting any payload.
  ClearErrors
  WriteRegStr HKCU "${ARP}" "InstallOwner" "${MARKER}"
  WriteRegStr HKCU "${ARP}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${ARP}" "InstallState" "incomplete"
  WriteRegStr HKCU "${ARP}" "DisplayName" "${DISPLAY_NAME} (incomplete - run Setup to repair)"
  WriteRegStr HKCU "${ARP}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "${ARP}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
  !insertmacro CheckWrite
  SetOutPath "$INSTDIR"
  !insertmacro CheckWrite
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  !insertmacro CheckWrite
  !include "${INSTALL_FILES_INCLUDE}"
  !insertmacro CheckWrite
  CreateDirectory "$SMPROGRAMS\${DISPLAY_NAME}"
  CreateShortcut "$SMPROGRAMS\${DISPLAY_NAME}\Rat-Trap Desktop Preview 2.lnk" "$INSTDIR\Rat-Trap-Desktop-Preview-2.exe"
  CreateShortcut "$SMPROGRAMS\${DISPLAY_NAME}\Read me first.lnk" "$INSTDIR\README-FIRST.txt"
  WriteRegStr HKCU "${ARP}" "DisplayName" "${DISPLAY_NAME}"
  WriteRegStr HKCU "${ARP}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${ARP}" "Publisher" "${OWNER}"
  WriteRegStr HKCU "${ARP}" "InstallOwner" "${MARKER}"
  WriteRegStr HKCU "${ARP}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${ARP}" "DisplayIcon" "$INSTDIR\Rat-Trap-Desktop-Preview-2.exe"
  WriteRegStr HKCU "${ARP}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "${ARP}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
  WriteRegDWORD HKCU "${ARP}" "NoModify" 1
  WriteRegDWORD HKCU "${ARP}" "NoRepair" 1
  WriteRegDWORD HKCU "${ARP}" "EstimatedSize" ${INSTALLED_KIB}
  !insertmacro CheckWrite
SectionEnd

Section /o "Offer Desktop Preview 2 in Open with for .gmw and .rtsf" Associations
  !insertmacro RegisterType ".gmw" "${GMW_PROGID}" "Rat-Trap Desktop Preview 2 GMW archive" "--open-archive"
  !insertmacro RegisterType ".rtsf" "${RTSF_PROGID}" "Rat-Trap Desktop Preview 2 Sealed File" "--open-sealed"
SectionEnd

Section /o "Desktop shortcut" DesktopShortcut
  ClearErrors
  CreateShortcut "$DESKTOP\${DISPLAY_NAME}.lnk" "$INSTDIR\Rat-Trap-Desktop-Preview-2.exe"
  !insertmacro CheckWrite
SectionEnd

Section "-Finish choices"
  ${If} ${SectionIsSelected} ${Associations}
    ClearErrors
    WriteRegDWORD HKCU "${ARP}" "OpenWithEnabled" 1
  ${Else}
    !insertmacro UnregisterType ".gmw" "${GMW_PROGID}" "--open-archive"
    !insertmacro UnregisterType ".rtsf" "${RTSF_PROGID}" "--open-sealed"
    ClearErrors
    WriteRegDWORD HKCU "${ARP}" "OpenWithEnabled" 0
  ${EndIf}
  !insertmacro CheckWrite
  ${If} ${SectionIsSelected} ${DesktopShortcut}
    ClearErrors
    WriteRegDWORD HKCU "${ARP}" "DesktopEnabled" 1
  ${Else}
    Delete "$DESKTOP\${DISPLAY_NAME}.lnk"
    ClearErrors
    WriteRegDWORD HKCU "${ARP}" "DesktopEnabled" 0
  ${EndIf}
  !insertmacro CheckWrite
  WriteRegStr HKCU "${ARP}" "InstallState" "complete"
  !insertmacro CheckWrite
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
  SetErrorLevel 0
SectionEnd

Function un.onInit
  SetShellVarContext current
  SetRegView 64
  ReadRegStr $0 HKCU "${ARP}" "InstallOwner"
  ReadRegStr $1 HKCU "${ARP}" "InstallLocation"
  ${If} $0 != "${MARKER}"
  ${OrIf} $1 != $INSTDIR
  ${OrIf} $INSTDIR != "$LOCALAPPDATA\Programs\Two Hands Network Ltd\${INSTALL_FOLDER}"
    MessageBox MB_OK|MB_ICONSTOP "This uninstaller does not match the registered Rat-Trap Desktop Preview 2 installation. No files were removed." /SD IDOK
    SetErrorLevel 3
    Quit
  ${EndIf}
  !insertmacro CheckBaseDirectories
  !insertmacro CheckPayloadUnlocked
FunctionEnd

Section "Uninstall"
  !insertmacro CheckBaseDirectories
  !insertmacro CheckPayloadUnlocked
  ; An explicit generated list: never recursively remove the app folder.
  !include "${UNINSTALL_FILES_INCLUDE}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\${DISPLAY_NAME}\Rat-Trap Desktop Preview 2.lnk"
  Delete "$SMPROGRAMS\${DISPLAY_NAME}\Read me first.lnk"
  RMDir "$SMPROGRAMS\${DISPLAY_NAME}"
  Delete "$DESKTOP\${DISPLAY_NAME}.lnk"
  !insertmacro UnregisterType ".gmw" "${GMW_PROGID}" "--open-archive"
  !insertmacro UnregisterType ".rtsf" "${RTSF_PROGID}" "--open-sealed"
  DeleteRegKey HKCU "${ARP}"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
  SetErrorLevel 0
  Goto uninstall_done
uninstall_failed:
  MessageBox MB_OK|MB_ICONSTOP "Some application files could not be removed. Close open files and run Uninstall again. The uninstaller and its registration have been kept." /SD IDOK
  SetErrorLevel 5
uninstall_done:
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${Application} "Installs or updates Desktop Preview 2 and its help files for your Windows account. Your Library catalogue, saved files and local diagnostics are preserved on removal."
  !insertmacro MUI_DESCRIPTION_TEXT ${Associations} "Adds Desktop Preview 2 to Open with. Your current default apps stay selected. Opening an archive preselects a screen; it does not decrypt or extract it."
  !insertmacro MUI_DESCRIPTION_TEXT ${DesktopShortcut} "Adds a Rat-Trap Desktop Preview 2 shortcut to your desktop."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function .onInit
  SetShellVarContext current
  SetRegView 64
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "Rat-Trap requires 64-bit Windows." /SD IDOK
    SetErrorLevel 2
    Quit
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "Rat-Trap requires Windows 10 or later." /SD IDOK
    SetErrorLevel 2
    Quit
  ${EndIf}
  ; A fixed, per-user app directory prevents /D from targeting user data.
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\Two Hands Network Ltd\${INSTALL_FOLDER}"
  !insertmacro CheckBaseDirectories
  ReadRegStr $0 HKCU "${ARP}" "InstallOwner"
  ReadRegStr $1 HKCU "${ARP}" "InstallLocation"
  StrCpy $ExistingInstallation 0
  ${If} $0 == "${MARKER}"
  ${AndIf} $1 == $INSTDIR
    StrCpy $ExistingInstallation 1
  ${ElseIf} $0 != ""
    MessageBox MB_OK|MB_ICONSTOP "An incompatible installer registration exists. Setup has made no changes." /SD IDOK
    SetErrorLevel 3
    Quit
  ${EndIf}
  ${If} $ExistingInstallation == 0
  ${AndIf} ${FileExists} "$INSTDIR\*.*"
    MessageBox MB_OK|MB_ICONSTOP "The Rat-Trap Desktop Preview 2 installation folder already contains files but is not registered to this installer. Setup has made no changes." /SD IDOK
    SetErrorLevel 3
    Quit
  ${EndIf}
  !insertmacro CheckPayloadUnlocked
  ; Preserve optional choices when this preview is reinstalled or repaired.
  ReadRegDWORD $0 HKCU "${ARP}" "OpenWithEnabled"
  ${If} $0 == 1
    !insertmacro SelectSection ${Associations}
  ${EndIf}
  ReadRegDWORD $0 HKCU "${ARP}" "DesktopEnabled"
  ${If} $0 == 1
    !insertmacro SelectSection ${DesktopShortcut}
  ${EndIf}
  ${GetParameters} $0
  ${GetOptions} $0 "/OPENWITH=" $AssociationArgument
  ${GetOptions} $0 "/DESKTOP=" $DesktopArgument
  ${If} $AssociationArgument == "1"
    !insertmacro SelectSection ${Associations}
  ${ElseIf} $AssociationArgument == "0"
    !insertmacro UnselectSection ${Associations}
  ${EndIf}
  ${If} $DesktopArgument == "1"
    !insertmacro SelectSection ${DesktopShortcut}
  ${ElseIf} $DesktopArgument == "0"
    !insertmacro UnselectSection ${DesktopShortcut}
  ${EndIf}
FunctionEnd
