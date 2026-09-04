@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PY_CMD="
set "PYTHONPATH=%~dp0.build_python;%PYTHONPATH%"

rem Prefer a normal Python installation over the Windows Store py alias.
rem The Store alias can import tkinter but does not ship Tcl/Tk archives,
rem which are required when embedding Tkinter in a one-file executable.
call :try_python_with_tk python
if defined PY_CMD goto python_found
call :try_python_with_tk py
if defined PY_CMD goto python_found

echo ERROR: No usable Python installation was found.
echo Install the standard Python 3.10+ distribution from python.org with Tkinter and Tcl/Tk files.
goto failed

:python_found
echo Using Python:
%PY_CMD% -c "import sys; print(sys.executable); print('Tk', __import__('tkinter').TkVersion)"

%PY_CMD% -c "import openpyxl" >nul 2>nul
if not errorlevel 1 goto pyinstaller_check

echo Installing openpyxl into the local build environment...
if not exist ".build_python" mkdir ".build_python"
%PY_CMD% -m pip install --disable-pip-version-check --target ".build_python" openpyxl
if errorlevel 1 goto failed

:pyinstaller_check
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

rem Python 3.14 ships Tcl/Tk library files as ZIP archives.  PyInstaller
rem cannot reliably discover those archives in a --onefile build, so unpack
rem the small script libraries into deterministic folders and add them below.
for /f "delims=" %%P in ('%PY_CMD% -c "import sys; print(sys.base_prefix)"') do set "PY_BASE=%%P"
if not defined PY_BASE (
  echo ERROR: Could not determine the Python installation directory.
  goto failed
)
set "TCL_ZIP="
set "TK_ZIP="
set "TCL_DIR="
set "TK_DIR="
for %%F in ("%PY_BASE%\tcl\libtcl*.zip") do if exist "%%~fF" set "TCL_ZIP=%%~fF"
for %%F in ("%PY_BASE%\tcl\libtk*.zip") do if exist "%%~fF" set "TK_ZIP=%%~fF"
for %%D in ("%PY_BASE%\tcl\tcl8.6" "%PY_BASE%\tcl\tcl8") do if exist "%%~fD" if not defined TCL_DIR set "TCL_DIR=%%~fD"
for %%D in ("%PY_BASE%\tcl\tk8.6" "%PY_BASE%\tcl\tk8") do if exist "%%~fD" if not defined TK_DIR set "TK_DIR=%%~fD"
if not defined TCL_ZIP if not defined TCL_DIR (
  echo ERROR: Tcl library archive/folder was not found under %PY_BASE%\tcl.
  goto failed
)
if not defined TK_ZIP if not defined TK_DIR (
  echo ERROR: Tk library archive/folder was not found under %PY_BASE%\tcl.
  goto failed
)
if exist ".build_tcl\tcl_library" rmdir /s /q ".build_tcl\tcl_library"
if exist ".build_tk\tk_library" rmdir /s /q ".build_tk\tk_library"
mkdir ".build_tcl\tcl_library" >nul
mkdir ".build_tk\tk_library" >nul
if defined TCL_ZIP (
  %PY_CMD% -c "import pathlib,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); out=pathlib.Path(sys.argv[2]); [((out.joinpath(*pathlib.PurePosixPath(n).parts[1:])).parent.mkdir(parents=True,exist_ok=True), out.joinpath(*pathlib.PurePosixPath(n).parts[1:]).write_bytes(z.read(n))) for n in z.namelist() if n.startswith('tcl_library/') and not n.endswith('/') and len(pathlib.PurePosixPath(n).parts)>1]" "%TCL_ZIP%" ".build_tcl\tcl_library"
  if errorlevel 1 goto failed
) else (
  xcopy "%TCL_DIR%\*" ".build_tcl\tcl_library" /E /I /Y >nul
  if errorlevel 1 goto failed
)
if defined TK_ZIP (
  %PY_CMD% -c "import pathlib,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); out=pathlib.Path(sys.argv[2]); [((out.joinpath(*pathlib.PurePosixPath(n).parts[1:])).parent.mkdir(parents=True,exist_ok=True), out.joinpath(*pathlib.PurePosixPath(n).parts[1:]).write_bytes(z.read(n))) for n in z.namelist() if n.startswith('tk_library/') and not n.endswith('/') and len(pathlib.PurePosixPath(n).parts)>1]" "%TK_ZIP%" ".build_tk\tk_library"
  if errorlevel 1 goto failed
) else (
  xcopy "%TK_DIR%\*" ".build_tk\tk_library" /E /I /Y >nul
  if errorlevel 1 goto failed
)

echo Building one EXE with all data embedded...
%PY_CMD% -m PyInstaller --noconfirm --clean --windowed --onefile --name TouhouVoteExplorer_Portable --add-data "data;data" --add-data ".build_tcl\tcl_library;_tcl_data" --add-data ".build_tk\tk_library;_tk_data" --distpath "dist\single_file" --workpath "build_single" app.py
if errorlevel 1 goto failed

if not exist "dist\single_file\TouhouVoteExplorer_Portable.exe" goto failed
rem Keep the legacy final_single location in sync for older launch shortcuts.
if exist "dist\final_single" copy /Y "dist\single_file\TouhouVoteExplorer_Portable.exe" "dist\final_single\TouhouVoteExplorer_Portable.exe" >nul
echo.
echo BUILD SUCCEEDED
echo SINGLE EXE: dist\single_file\TouhouVoteExplorer_Portable.exe
echo Send this EXE by itself. The recipient does not need Python or data files.
pause
exit /b 0

:try_python_with_tk
rem %~1 may be either `python`, `py`, or a quoted full path.
"%~1" -c "import pathlib,sys,tkinter; t=pathlib.Path(sys.base_prefix)/'tcl'; assert ((list(t.glob('libtcl*.zip')) and list(t.glob('libtk*.zip'))) or (any((t/n).is_dir() for n in ('tcl8.6','tcl8')) and any((t/n).is_dir() for n in ('tk8.6','tk8'))))" >nul 2>nul
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
