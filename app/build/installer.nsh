; The app registers voxwell:// for itself when it runs, so the uninstaller has to take that away too.
!macro customUnInstall
  DeleteRegKey HKCU "Software\Classes\voxwell"
!macroend
