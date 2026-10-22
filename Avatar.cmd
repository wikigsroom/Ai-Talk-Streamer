@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Avatar.ps1" %*
exit /b %ERRORLEVEL%
