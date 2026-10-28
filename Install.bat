@echo off
rem Create tools\venv with pyMHF + NMS.py for the galaxy map mod (needs Python 3.13 x64).
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (py -3.13 -m venv tools\venv) || (python -m venv tools\venv)
if errorlevel 1 (echo Python 3.13 not found - install it from python.org & pause & exit /b 1)
tools\venv\Scripts\python.exe -m pip install -q --upgrade pip
tools\venv\Scripts\python.exe -m pip install -q -r requirements.txt
if errorlevel 1 (echo pip install failed & pause & exit /b 1)
echo.
echo Done. Steam - No Man's Sky - Properties - Launch options:
echo     "%~dp0launch.cmd" %%command%%
pause
