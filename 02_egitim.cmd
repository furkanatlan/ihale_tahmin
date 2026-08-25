@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp002_egitim.ps1"
exit /b %errorlevel%
