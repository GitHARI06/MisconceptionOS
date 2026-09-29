# MisconceptionOS Unified Startup Script
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " 🚀 Starting MisconceptionOS (EduGenAI Challenge 2 MVP)" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan

# Start Backend FastAPI Server
Write-Host "Starting FastAPI Backend Server on http://127.0.0.1:8000..." -ForegroundColor Yellow
$backendProcess = Start-Process -FilePath "python" -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload" -WorkingDirectory "C:\MGH]\misconception_os\backend" -PassThru

# Start Frontend Vite Dev Server
Write-Host "Starting React + Vite Frontend on http://localhost:3000..." -ForegroundColor Yellow
$frontendProcess = Start-Process -FilePath "npm" -ArgumentList "--prefix `"C:\MGH]\misconception_os\frontend`" run dev" -PassThru

Write-Host "`n✨ MisconceptionOS is running!" -ForegroundColor Green
Write-Host "👉 Student Voice Studio & Teacher HUD: http://localhost:3000" -ForegroundColor White
Write-Host "👉 Backend API Docs: http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host "`nPress Ctrl+C or close the terminal windows to exit.`n"
