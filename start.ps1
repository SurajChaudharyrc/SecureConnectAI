# SecureConnect-AI: one-command start (Windows / PowerShell)
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}

$pip = ".venv\Scripts\pip.exe"
$python = ".venv\Scripts\python.exe"

Write-Host "Installing dependencies (this can take a few minutes the first time)..." -ForegroundColor Cyan
& $pip install --upgrade pip > $null
& $pip install -r backend/requirements.txt

if (-not (Test-Path "backend/.env")) {
    Copy-Item "backend/.env.example" "backend/.env"
    Write-Host "Created backend/.env from .env.example (edit APP_SECRET for prod)." -ForegroundColor Yellow
}

Write-Host "Seeding demo data..." -ForegroundColor Cyan
& $python -m backend.seed

Write-Host "Starting server at http://localhost:8000 ..." -ForegroundColor Green
& $python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
