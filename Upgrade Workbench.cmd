@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -B -X utf8 "scripts\upgrade_workbench.py" wizard
) else (
  py -3.12 -B -X utf8 "scripts\upgrade_workbench.py" wizard
)
set "workbench_upgrade_exit=%errorlevel%"
pause
exit /b %workbench_upgrade_exit%
