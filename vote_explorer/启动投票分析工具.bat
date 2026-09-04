@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Prefer a packaged build when one is present.  This keeps a machine with
rem Python installed from accidentally launching the source tree instead of
rem the self-contained release the user intended to share.
if exist "dist\TouhouVoteExplorer\TouhouVoteExplorer.exe" goto run_exe
if exist "dist\single_file\TouhouVoteExplorer_Portable.exe" goto run_single_exe

where pyw >nul 2>nul
if not errorlevel 1 goto run_pyw

where pythonw >nul 2>nul
if not errorlevel 1 goto run_pythonw

where py >nul 2>nul
if not errorlevel 1 goto run_py

where python >nul 2>nul
if not errorlevel 1 goto run_python

echo ERROR: Python was not found.
echo Install Python 3.10 or newer from python.org and enable Add Python to PATH.
pause
exit /b 1

:run_exe
start "" "dist\TouhouVoteExplorer\TouhouVoteExplorer.exe"
exit /b 0

:run_single_exe
start "" "dist\single_file\TouhouVoteExplorer_Portable.exe"
exit /b 0

:run_pyw
start "" pyw app.pyw
exit /b 0

:run_pythonw
start "" pythonw app.pyw
exit /b 0

:run_py
py app.py
if errorlevel 1 goto launch_failed
exit /b 0

:run_python
python app.py
if errorlevel 1 goto launch_failed
exit /b 0

:launch_failed
echo.
echo ERROR: The application failed to start.
echo See launcher_error.log in this folder for details.
pause
exit /b 1
