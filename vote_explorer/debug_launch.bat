@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo Vote Explorer diagnostic launcher
echo Working directory: %CD%
echo.

where py >nul 2>nul
if not errorlevel 1 goto use_py

where python >nul 2>nul
if not errorlevel 1 goto use_python

echo ERROR: Python was not found on PATH.
goto done

:use_py
py --version
py -c "import tkinter; print('Tkinter', tkinter.TkVersion)"
if errorlevel 1 goto done
py app.py
goto done

:use_python
python --version
python -c "import tkinter; print('Tkinter', tkinter.TkVersion)"
if errorlevel 1 goto done
python app.py

:done
echo.
echo Diagnostic run finished. Review the output above.
pause
