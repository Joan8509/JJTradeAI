$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "venv\Scripts\python.exe"
$logDirectory = Join-Path $projectRoot "exports"
$stdoutLog = Join-Path $logDirectory "streamlit.stdout.log"
$stderrLog = Join-Path $logDirectory "streamlit.stderr.log"

if (-not (Test-Path -LiteralPath $python)) {
    throw "No existe el Python del entorno virtual: $python"
}

$client = New-Object System.Net.Sockets.TcpClient
try {
    $connection = $client.ConnectAsync("127.0.0.1", 8501)
    if ($connection.Wait(2000) -and $client.Connected) {
        exit 0
    }
}
catch {
    # Connection refused means the application needs to start.
}
finally {
    $client.Dispose()
}

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
Start-Process `
    -FilePath $python `
    -ArgumentList @("-m", "streamlit", "run", "app.py", "--server.address", "127.0.0.1", "--server.port", "8501") `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog
