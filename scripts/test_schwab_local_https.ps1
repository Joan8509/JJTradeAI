# Creates/trusts only this Administrator's nonexportable loopback certificate.
# Starts a credential-free receiver, tests TLS strictly, then stops its own tree.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$stop = Join-Path $root 'exports\private_runtime\schwab_https.stop'
$runner = $null
$receiptPath = Join-Path $root 'exports\private_runtime\schwab_https.runtime.json'
try {
    # Never probe or stop a receiver that this test does not own.
    foreach ($port in @(8182,8183)) {
        $probe = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,$port)
        try { $probe.Start() } finally { $probe.Stop() }
    }
    $runner = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-NonInteractive','-File',
        ('"'+(Join-Path $PSScriptRoot 'start_schwab_local_https.ps1')+'"'),
        '-PrepareCertificate','-HealthOnly','-DurationSeconds','90') -WorkingDirectory $root -WindowStyle Hidden -PassThru
    $ready = $false
    for ($attempt=0; $attempt -lt 40; $attempt++) {
        if ($runner.HasExited) { throw 'Receiver stopped before readiness' }
        if (Test-Path -LiteralPath $receiptPath) {
            $receipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
            $ready = $receipt.pid -eq $runner.Id -and $receipt.state -eq 'LOCAL_LISTENER_STARTING'
        }
        if ($ready) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'Local listener unavailable' }
    Start-Sleep -Milliseconds 200
    & (Join-Path $root 'venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'check_schwab_local_https.py')
    if ($LASTEXITCODE -ne 0) { throw 'Local HTTPS verification failed' }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 8182,8183)
    if ($listeners.Count -ne 2 -or @($listeners | Where-Object {$_.LocalAddress -ne '127.0.0.1'}).Count -ne 0) {
        throw 'Unexpected listener exposure'
    }
    [pscustomobject]@{local_loopback_listeners=2;non_loopback_listeners=0;real_orders_enabled=$false} | ConvertTo-Json -Compress
} finally {
    if ($runner -and -not $runner.HasExited) {
        [IO.File]::WriteAllText($stop,'stop local test')
        if (-not $runner.WaitForExit(10000)) { & taskkill.exe /PID $runner.Id /T /F *> $null }
    }
    $remaining = @(Get-NetTCPConnection -State Listen -LocalPort 8182,8183 -ErrorAction SilentlyContinue)
    [pscustomobject]@{local_test_stopped=($remaining.Count -eq 0);remaining_listeners=$remaining.Count} | ConvertTo-Json -Compress
}
