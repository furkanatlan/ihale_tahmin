@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp003_uygulamayi_baslat.ps1"
exit /b %errorlevel%
