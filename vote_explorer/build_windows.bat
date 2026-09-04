@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PY_CMD="
set "PYTHONPATH=%~dp0.build_python;%PYTHONPATH%"

rem Prefer a normal Python installation over the Windows Store py alias.
call :try_python_with_tk python
if defined PY_CMD goto python_found
call :try_python_with_tk py
if defined PY_CMD goto python_found

echo ERROR: No usable Python installation was found.
echo Install the standard Python 3.10+ distribution from python.org with Tkinter enabled.
goto failed

:python_found
echo Using Python:
%PY_CMD% -c "import sys; print(sys.executable); print('Tk', __import__('tkinter').TkVersion)"

%PY_CMD% -c "import openpyxl" >nul 2>nul
if not errorlevel 1 goto dependencies_ready

echo Installing openpyxl into the local build environment...
if not exist ".build_python" mkdir ".build_python"
%PY_CMD% -m pip install --disable-pip-version-check --target ".build_python" openpyxl
if errorlevel 1 goto failed

:dependencies_ready
%PY_CMD% -m pip show pyinstaller >nul 2>nul
if not errorlevel 1 goto build

echo Installing PyInstaller...
if not exist ".build_python" mkdir ".build_python"
%PY_CMD% -m pip install --disable-pip-version-check --target ".build_python" pyinstaller
if errorlevel 1 goto failed

:build
echo Rebuilding bundled vote and analysis data...
%PY_CMD% "%~dp0..\scripts_pipeline\build_vote_dataset.py"
if errorlevel 1 goto failed
%PY_CMD% "%~dp0..\scripts_pipeline\build_vote_explorer_analysis_data.py"
if errorlevel 1 goto failed
echo Splitting large CSV data files for repository compatibility...
%PY_CMD% "%~dp0..\scripts_pipeline\split_large_files.py" --all --replace
if errorlevel 1 goto failed

echo Building the portable Windows application...
%PY_CMD% -m PyInstaller --noconfirm --clean --windowed --onedir --name TouhouVoteExplorer app.py
if errorlevel 1 goto failed

if not exist "dist\TouhouVoteExplorer\TouhouVoteExplorer.exe" goto failed
echo Copying data beside the portable EXE...
if not exist "dist\TouhouVoteExplorer\data" mkdir "dist\TouhouVoteExplorer\data"
xcopy "data\*" "dist\TouhouVoteExplorer\data" /E /I /Y >nul
if errorlevel 1 goto failed
if not exist "dist\TouhouVoteExplorer\data\analysis_data_manifest.json" goto failed
rem Keep the legacy final_onedir location in sync for older launch shortcuts.
if exist "dist\final_onedir\TouhouVoteExplorer" (
  xcopy "dist\TouhouVoteExplorer\*" "dist\final_onedir\TouhouVoteExplorer" /E /I /Y >nul
  if errorlevel 1 goto failed
)
echo.
echo BUILD SUCCEEDED
echo EXE: dist\TouhouVoteExplorer\TouhouVoteExplorer.exe
echo Send the whole dist\TouhouVoteExplorer folder to other users.
pause
exit /b 0

:try_python_with_tk
rem %~1 may be either `python`, `py`, or a quoted full path.
"%~1" -c "import sys,tkinter; print(tkinter.TkVersion)" >nul 2>nul
if errorlevel 1 exit /b 0
set "PY_CMD=%~1"
exit /b 0

:no_tkinter
echo.
echo ERROR: Tkinter is unavailable in this Python installation.
echo Install the standard Windows Python distribution from python.org.
goto failed

:failed
echo.
echo BUILD FAILED. Review the messages above.
pause
exit /b 1
