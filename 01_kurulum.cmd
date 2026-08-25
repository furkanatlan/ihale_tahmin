@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp001_kurulum.ps1"
exit /b %errorlevel%
