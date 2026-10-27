@echo off
powershell.exe -NoProfile -File "%~dp099_SISTEM\buka_studio.ps1" -Lanjutkan
if errorlevel 1 pause
