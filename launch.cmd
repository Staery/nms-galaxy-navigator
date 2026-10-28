@echo off
rem Start NMS with the NMS.py mod.
rem Steam -> No Man's Sky -> Properties -> Launch options:
rem     "<repo folder>\launch.cmd" %command%
rem Without arguments (shortcut) the game is started via Steam.
setlocal
set "ROOT=%~dp0"
set "MOD=%ROOT%mod\galaxy_list.py"
rem prototype with probes: mod\proto_map.py
if not exist "%ROOT%logs" mkdir "%ROOT%logs"

if "%~1"=="" (start "" "steam://rungameid/275850") else (start "" %*)

rem wait for the game process (up to 3 minutes)
set /a N=0
:wait
tasklist /FI "IMAGENAME eq NMS.exe" 2>nul | find /I "NMS.exe" >nul && goto run
set /a N+=1
if %N% GEQ 90 (echo %date% %time% NMS.exe not found >> "%ROOT%logs\launcher.log" & exit /b 1)
ping -n 3 127.0.0.1 >nul
goto wait

:run
rem right after start NMS.exe has no module list yet -> pymhf gets base None and no hooks; wait for the game window
set /a N=0
:waitwin
tasklist /V /FI "IMAGENAME eq NMS.exe" /FO CSV /NH 2>nul | find /I "No Man" >nul && goto ready
set /a N+=1
if %N% GEQ 60 goto ready
ping -n 3 127.0.0.1 >nul
goto waitwin
:ready
ping -n 4 127.0.0.1 >nul
echo %date% %time% start mod %MOD% >> "%ROOT%logs\launcher.log"
rem pymhf needs a real console on stdout (prompt_toolkit), so only stderr goes to the log
title NMS.py mod - keep this window open while playing
"%ROOT%tools\venv\Scripts\pymhf.exe" run "%MOD%" 2>> "%ROOT%logs\launcher.log"
echo %date% %time% pymhf exited, code %errorlevel% >> "%ROOT%logs\launcher.log"
