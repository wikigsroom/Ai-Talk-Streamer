@echo off
cd /d "%~dp0"
"runtime\livetalking\Scripts\python.exe" -X utf8 -B "scripts\start_studio.py"
if errorlevel 1 pause
