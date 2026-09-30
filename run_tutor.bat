@echo off
REM One-click launcher for MisconceptionOS (LearnAble Physics Tutor).
REM Installs any missing Python packages, checks Ollama, starts the backend
REM and frontend in their own windows, and opens the app in your browser.
REM Logs are written to the "logs" folder next to this file.

setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
set LOG=%~dp0logs\launcher.log
echo ==== %date% %time% ==== > "%LOG%"

echo [1/5] Checking Python...
python --version >> "%LOG%" 2>&1 || (echo Python was not found on PATH. & echo Python not found >> "%LOG%" & pause & exit /b 1)

echo [2/5] Installing/updating backend packages (first run can take a few minutes)...
python -m pip install -q -r backend\requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (echo pip reported a problem - see logs\launcher.log & echo PIP FAILED >> "%LOG%") else (echo PIP OK >> "%LOG%")

echo [3/5] Checking Ollama...
where ollama >> "%LOG%" 2>&1
if errorlevel 1 (
  echo Ollama not found - the tutor will use its built-in fallback replies.
  echo OLLAMA NOT FOUND >> "%LOG%"
) else (
  curl -s -o nul http://localhost:11434/api/tags || start "Ollama" /min ollama serve
  timeout /t 3 /nobreak > nul
  ollama list >> "%LOG%" 2>&1
)

echo [4/5] Starting backend and frontend...
REM Stop a copy that is already running, so double-clicking again restarts cleanly.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do taskkill /PID %%p /F > nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3000 " ^| findstr LISTENING') do taskkill /PID %%p /F > nul 2>&1
taskkill /FI "WINDOWTITLE eq MisconceptionOS backend*" /T /F > nul 2>&1
taskkill /FI "WINDOWTITLE eq MisconceptionOS frontend*" /T /F > nul 2>&1
timeout /t 2 /nobreak > nul
if not exist frontend\node_modules (
  echo Installing frontend packages...
  call npm --prefix frontend install >> "%LOG%" 2>&1
)
start "MisconceptionOS backend" powershell -NoExit -Command "Set-Location '%~dp0backend'; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 2>&1 | Tee-Object -FilePath '%~dp0logs\backend.log'"
start "MisconceptionOS frontend" powershell -NoExit -Command "Set-Location '%~dp0frontend'; npm run dev 2>&1 | Tee-Object -FilePath '%~dp0logs\frontend.log'"

echo [5/5] Waiting for the servers...
set /a tries=0
:wait
set /a tries+=1
timeout /t 2 /nobreak > nul
curl -s -o nul -w "%%{http_code}" http://127.0.0.1:8000/ > "%TEMP%\mos_code.txt" 2>nul
set /p CODE=<"%TEMP%\mos_code.txt"
if not "%CODE%"=="200" if %tries% lss 45 goto wait
echo Backend status: %CODE% >> "%LOG%"
curl -s -o nul http://localhost:3000/ >> "%LOG%" 2>&1
echo READY >> "%LOG%"

start "" http://localhost:3000
echo.
echo MisconceptionOS is running:  http://localhost:3000
echo Keep the backend and frontend windows open. Close them to stop the app.
timeout /t 8 > nul
