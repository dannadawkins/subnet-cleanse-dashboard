# Starts Site ID API (WSL), FastAPI backend and Next.js frontend. Ctrl+C stops all.
param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    $node = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS*\node-*" -Directory -ErrorAction SilentlyContinue |
        Select-Object -Last 1
    if (-not $node) { throw 'Node.js was not found. Install it with: winget install OpenJS.NodeJS.LTS' }
    $env:Path = "$($node.FullName);$env:Path"
}

$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host 'Creating backend virtual environment...'
    py -m venv (Join-Path $root 'backend\.venv')
    & $python -m pip install -q -r (Join-Path $root 'backend\requirements.txt')
}
if (-not (Test-Path (Join-Path $root 'frontend\node_modules'))) {
    Write-Host 'Installing frontend dependencies...'
    Push-Location (Join-Path $root 'frontend'); npm install; Pop-Location
}

$siteScript = (Resolve-Path (Join-Path $root '..\api\start_api.sh')).Path
$wslScript = '/mnt/' + $siteScript.Substring(0, 1).ToLower() + ($siteScript.Substring(2) -replace '\\', '/')

$site = Start-Process wsl.exe -ArgumentList 'bash', "`"$wslScript`"" -NoNewWindow -PassThru `
    -RedirectStandardOutput "$logs\site_id_api.log" -RedirectStandardError "$logs\site_id_api.err.log"
$web = Start-Process npm.cmd -ArgumentList 'run', 'dev', '--', '-H', '127.0.0.1' -WorkingDirectory (Join-Path $root 'frontend') -NoNewWindow -PassThru `
    -RedirectStandardOutput "$logs\frontend.log" -RedirectStandardError "$logs\frontend.err.log"

Write-Host ''
Write-Host 'Subnet Cleanse is starting:'
Write-Host '  App:         http://localhost:3000'
Write-Host '  Backend API: http://localhost:8000/docs'
Write-Host '  Site ID API: http://localhost:8800 (logs in .\logs)'
Write-Host 'Press Ctrl+C to stop everything.'
Write-Host ''

if (-not $NoBrowser) { Start-Job { Start-Sleep 8; Start-Process 'http://localhost:3000' } | Out-Null }
try {
    & $python -m uvicorn app.main:app --app-dir (Join-Path $root 'backend') --port 8000
}
finally {
    foreach ($process in $web, $site) {
        if ($process -and -not $process.HasExited) { taskkill /PID $process.Id /T /F 2>&1 | Out-Null }
    }
    Write-Host 'Stopped.'
}
