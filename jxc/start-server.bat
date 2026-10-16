@echo off
cd /d %~dp0
pocketbase.exe serve --http=0.0.0.0:8090
pause
