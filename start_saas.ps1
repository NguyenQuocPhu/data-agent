# start_saas.ps1
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   LAMBDA SaaS POC - Startup Script" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Start FastAPI Backend in background (using WSL since Python is there)
Write-Host "[1/2] Starting FastAPI Backend on port 8000 (via WSL)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "wsl bash -i -c 'python api_server.py'" -WindowStyle Normal

# Wait a couple of seconds to let backend initialize
Start-Sleep -Seconds 2

# 2. Start Next.js Frontend (using Windows native Node.js)
Write-Host "[2/2] Starting Next.js Frontend on port 3000 (via Windows)..." -ForegroundColor Yellow
Set-Location "ui\deepanalyze_frontend"
if (Get-Command "pnpm" -ErrorAction SilentlyContinue) {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "pnpm run dev" -WindowStyle Normal
} else {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "npm run dev" -WindowStyle Normal
}

Write-Host "==========================================" -ForegroundColor Green
Write-Host " SaaS POC is running!" -ForegroundColor Green
Write-Host " Backend API : http://localhost:8000" -ForegroundColor White
Write-Host " UI Dashboard: http://localhost:3000" -ForegroundColor White
Write-Host "==========================================" -ForegroundColor Green
Write-Host "To stop the servers, close the newly opened PowerShell windows." -ForegroundColor Gray
