@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
  py -3 server.py --port 8765 --open
  goto :eof
)

where python >nul 2>nul
if not errorlevel 1 (
  python server.py --port 8765 --open
  goto :eof
)

where python3 >nul 2>nul
if not errorlevel 1 (
  python3 server.py --port 8765 --open
  goto :eof
)

echo Python 3 was not found. Install Python 3 and run this file again.
pause
exit /b 1
