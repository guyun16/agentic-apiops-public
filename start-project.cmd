@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-project.ps1" %*
if errorlevel 1 (
  echo Startup failed. See .local-run logs and the message above.
  pause
)
