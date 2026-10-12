$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "venv\Scripts\python.exe"
$logDirectory = Join-Path $projectRoot "exports"
$stdoutLog = Join-Path $logDirectory "streamlit.stdout.log"
$stderrLog = Join-Path $logDirectory "streamlit.stderr.log"

if (-not (Test-Path -LiteralPath $python)) {
    throw "No existe el Python del entorno virtual: $python"
}

$listener = Get-NetTCPConnection -State Listen -LocalPort 8501 -ErrorAction SilentlyContinue
if ($listener) {
    exit 0
}

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
Start-Process `
    -FilePath $python `
    -ArgumentList @("-m", "streamlit", "run", "app.py", "--server.port", "8501") `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog