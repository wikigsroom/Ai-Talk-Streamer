@echo off
cd /d "%~dp0"
python -B -X utf8 manage_stack.py start
if errorlevel 1 pause
