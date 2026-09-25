# Starts the API and static UI on separate local ports.
$projectRoot = $PSScriptRoot
$python = Get-Command py -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }

$backend = Join-Path $projectRoot "backend"
$frontend = Join-Path $projectRoot "project"
Start-Process -FilePath "node" -ArgumentList "serve-local.js" -WorkingDirectory $frontend -WindowStyle Hidden
if ($python) {
  Start-Process -FilePath $python.Source -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8001" -WorkingDirectory $backend -WindowStyle Hidden
} else {
  Write-Warning "The frontend started, but Python 3 was not found so the backend is not running."
}

Write-Host "RIIS is starting. Open http://127.0.0.1:5173 once both services are ready."
