@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "PY_CMD="
set "PYTHONPATH=%~dp0.build_python;%PYTHONPATH%"

rem Prefer a normal Python installation over the Windows Store py alias.
call :try_python python
if defined PY_CMD goto dependencies
call :try_python py
if defined PY_CMD goto dependencies

echo ERROR: No usable Python installation was found.
echo Install the standard Python 3.10+ distribution from python.org and ensure openpyxl is available.
goto failed

:dependencies
%PY_CMD% -c "import openpyxl" >nul 2>nul
if not errorlevel 1 goto run
echo Installing openpyxl into the local build environment...
if not exist "%~dp0.build_python" mkdir "%~dp0.build_python"
%PY_CMD% -m pip install --disable-pip-version-check --target "%~dp0.build_python" openpyxl
if errorlevel 1 goto failed

:run
%PY_CMD% scripts_pipeline\build_vote_dataset.py
if errorlevel 1 goto failed
%PY_CMD% scripts_pipeline\build_vote_explorer_analysis_data.py
if errorlevel 1 goto failed
echo Splitting large CSV data files for repository compatibility...
%PY_CMD% scripts_pipeline\split_large_files.py --all --replace
if errorlevel 1 goto failed

if not exist "%~dp0dist\TouhouVoteExplorer\TouhouVoteExplorer.exe" goto succeeded
echo Syncing rebuilt data to the existing portable folder...
if not exist "%~dp0dist\TouhouVoteExplorer\data" mkdir "%~dp0dist\TouhouVoteExplorer\data"
xcopy "%~dp0data\*" "%~dp0dist\TouhouVoteExplorer\data" /E /I /Y >nul
if errorlevel 1 goto failed

rem Keep previously built releases working until they are rebuilt with the
rem new external-data lookup. New releases use the data folder beside the EXE.
if not exist "%~dp0dist\TouhouVoteExplorer\_internal\data" goto sync_legacy
xcopy "%~dp0data\*" "%~dp0dist\TouhouVoteExplorer\_internal\data" /E /I /Y >nul
if errorlevel 1 goto failed

:sync_legacy
rem Also refresh the older final_onedir release folder when present.
if not exist "%~dp0dist\final_onedir\TouhouVoteExplorer\data" goto synced
xcopy "%~dp0data\*" "%~dp0dist\final_onedir\TouhouVoteExplorer\data" /E /I /Y >nul
if errorlevel 1 goto failed

:synced
echo Existing portable data was updated.

:succeeded
echo.
echo Analysis data build succeeded.
pause
exit /b 0

:failed
echo.
echo Analysis data build failed. Review the messages above.
pause
exit /b 1

:try_python
rem Only accept an interpreter that can read the workbook source files.
"%~1" -c "import openpyxl" >nul 2>nul
if errorlevel 1 exit /b 0
set "PY_CMD=%~1"
exit /b 0
