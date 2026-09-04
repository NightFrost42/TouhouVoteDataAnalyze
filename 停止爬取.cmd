@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "CRAWL_PYTHON="
if exist "%~dp0.venv\Scripts\python.exe" goto use_venv_python
for /f "delims=" %%P in ('where python.exe 2^>nul') do (
  set "CRAWL_PYTHON=%%P"
  goto python_ready
)
goto python_missing

:use_venv_python
set "CRAWL_PYTHON=%~dp0.venv\Scripts\python.exe"
goto python_ready

:python_missing
echo [错误] 找不到可用的 python.exe。请安装 Python。
pause
exit /b 1

:python_ready
"%CRAWL_PYTHON%" -c "import sys" >nul 2>&1
if errorlevel 1 goto python_missing

"%CRAWL_PYTHON%" "%~dp0scripts_pipeline\data_crawl_control.py" stop --timeout 120
if errorlevel 1 (
  echo [错误] 安全停机未完成，请查看上面的详细信息。
  pause
  exit /b 1
)
exit /b 0
