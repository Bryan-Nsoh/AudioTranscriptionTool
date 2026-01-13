@echo off
cd /d "%~dp0"
start "" /min ".venv\Scripts\pythonw.exe" "src\transcribe_gui.py"
