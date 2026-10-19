@echo off
cd /d %~dp0
set PY=pythonw
if exist "%~dp0.venv\Scripts\pythonw.exe" set PY=%~dp0.venv\Scripts\pythonw.exe
if exist "%~dp0..\runtime\python\pythonw.exe" set PY=%~dp0..\runtime\python\pythonw.exe
"%PY%" "%~dp0heal.py" --all
