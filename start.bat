@echo off
echo ===========================================
echo Starting Proxy Sentinel Services...
echo ===========================================

echo.
echo Starting Backend API...
start "Proxy Sentinel Backend" cmd /k "cd /d "%~dp0backend" && set HOST=127.0.0.1&& set PORT=8000&& py main.py"

echo.
echo Starting Frontend UI...
start "Proxy Sentinel Frontend" cmd /k "cd /d "%~dp0frontend" && npm install && npm run dev -- --host 127.0.0.1 --port 5173"

echo.
echo Both services are now booting up in separate windows!
echo Backend API: http://127.0.0.1:8000
echo Frontend UI: http://127.0.0.1:5173
echo.
pause
