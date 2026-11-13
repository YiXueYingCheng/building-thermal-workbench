@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please create .venv and install requirements-lock.txt first. See README.md.
  pause
  exit /b 1
)
if not exist "building-workbench-next\config.json" copy /y "building-workbench-next\config.example.json" "building-workbench-next\config.json" >nul
".venv\Scripts\python.exe" -B -X utf8 "building-workbench-next\launch.py"
if errorlevel 1 pause
endlocal
