@echo off
rem Settings window of the mod (features and stat weights). Changes apply in game within a few seconds.
cd /d "%~dp0"
if exist tools\venv\Scripts\pythonw.exe (start "" tools\venv\Scripts\pythonw.exe settings_gui.py & exit /b)
where pyw >nul 2>nul && (start "" pyw -3 settings_gui.py & exit /b)
start "" pythonw settings_gui.py
