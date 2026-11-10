@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo 未找到虚拟环境，请先双击 install_windows.bat
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m PyInstaller --noconfirm --clean CodeScanner.spec
echo.
echo 封装完成：dist\CodeScanner.exe
pause
