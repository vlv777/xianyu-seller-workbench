@echo off
chcp 65001 >nul
cd /d %~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0µÍ∆Ãπ‹¿Ì.ps1" -Action start-all
pause
