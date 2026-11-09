@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo 安装完成。双击 run_windows.bat 启动，或运行 build_windows.bat 封装 EXE。
pause
