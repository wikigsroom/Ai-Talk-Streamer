@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\livetalking\Scripts\python.exe" (
  echo Run Setup-Streamer.ps1 -PrepareAvatar -HardwareProfile rtx3080-original first.
  pause
  exit /b 1
)
if not exist "configs\hardware-profile.json" (
  "runtime\livetalking\Scripts\python.exe" -X utf8 -B "scripts\hardware_profile.py" rtx3080-original
  if errorlevel 1 exit /b 1
)
"runtime\livetalking\Scripts\python.exe" -X utf8 -B "scripts\start_studio.py"
if errorlevel 1 pause
