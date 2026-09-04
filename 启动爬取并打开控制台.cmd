@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "CRAWL_PYTHON="
set "CRAWL_PYTHONW="
if exist "%~dp0.venv\Scripts\python.exe" if exist "%~dp0.venv\Scripts\pythonw.exe" goto use_venv_python
for /f "delims=" %%P in ('where python.exe 2^>nul') do (
  set "CRAWL_PYTHON=%%P"
  goto use_path_python
)
goto python_missing

:use_venv_python
set "CRAWL_PYTHON=%~dp0.venv\Scripts\python.exe"
set "CRAWL_PYTHONW=%~dp0.venv\Scripts\pythonw.exe"
goto python_ready

:use_path_python
for %%D in ("%CRAWL_PYTHON%") do set "CRAWL_PYTHONW=%%~dpDpythonw.exe"
if not exist "%CRAWL_PYTHONW%" goto python_missing
goto python_ready

:python_missing
echo [错误] 找不到可用的 python.exe/pythonw.exe。请安装 Python。
pause
exit /b 1

:python_ready
"%CRAWL_PYTHON%" -c "import sys" >nul 2>&1
if errorlevel 1 goto python_missing

"%CRAWL_PYTHON%" "%~dp0scripts_pipeline\data_crawl_control.py" start
if errorlevel 1 (
  echo [错误] 抓取队列启动失败，请查看上面的详细信息。
  pause
  exit /b 1
)

start "东方投票数据抓取控制台" "%CRAWL_PYTHONW%" "%~dp0scripts_pipeline\data_crawl_dashboard.py" --open-browser
if errorlevel 1 (
  echo [错误] 无法启动抓取控制台。
  pause
  exit /b 1
)
"%CRAWL_PYTHON%" "%~dp0scripts_pipeline\data_crawl_dashboard.py" --health-check --wait-seconds 10
if errorlevel 1 (
  echo [错误] 抓取队列已启动，但控制台没有在 10 秒内就绪。
  pause
  exit /b 1
)
exit /b 0
