# Credential-free TLS test on account ports only, preserving the data receiver.
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$stop=Join-Path $root 'exports\private_runtime\schwab_accounts_https.stop'
$receiptPath=Join-Path $root 'exports\private_runtime\schwab_accounts_https.runtime.json'
$runner=$null
try {
    foreach ($port in @(8186,8187)) {
        $probe=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,$port)
        try {$probe.Start()} finally {$probe.Stop()}
    }
    $runner=Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-NonInteractive','-File',
        ('"'+(Join-Path $PSScriptRoot 'start_schwab_accounts_https.ps1')+'"'),'-HealthOnly','-DurationSeconds','60') -WorkingDirectory $root -WindowStyle Hidden -PassThru
    $ready=$false
    for ($attempt=0;$attempt -lt 40;$attempt++) {
        if ($runner.HasExited) {throw 'Account receiver stopped'}
        if (Test-Path -LiteralPath $receiptPath) {
            $receipt=Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
            $ready=$receipt.pid -eq $runner.Id -and $receipt.state -eq 'STARTING'
        }
        if ($ready) {break}
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {throw 'Account receiver unavailable'}
    Start-Sleep -Milliseconds 200
    & (Join-Path $root 'venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'check_schwab_accounts_https.py')
    if ($LASTEXITCODE -ne 0) {throw 'Account TLS check failed'}
    $listeners=@(Get-NetTCPConnection -State Listen -LocalPort 8186,8187)
    if ($listeners.Count -ne 2 -or @($listeners|Where-Object {$_.LocalAddress -ne '127.0.0.1'}).Count) {throw 'Exposure mismatch'}
    @{local_loopback_listeners=2;non_loopback_listeners=0;real_orders_enabled=$false}|ConvertTo-Json -Compress
} finally {
    if ($runner -and -not $runner.HasExited) {
        [IO.File]::WriteAllText($stop,'stop account health test')
        if (-not $runner.WaitForExit(10000)) {& taskkill.exe /PID $runner.Id /T /F *> $null}
    }
    $remaining=@(Get-NetTCPConnection -State Listen -LocalPort 8186,8187 -ErrorAction SilentlyContinue)
    @{account_test_stopped=($remaining.Count -eq 0);remaining_listeners=$remaining.Count}|ConvertTo-Json -Compress
}
