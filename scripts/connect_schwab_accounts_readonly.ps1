# Run in an interactive PowerShell console in the VPS, after app approval.
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$pythonPath=Join-Path $projectRoot 'venv\Scripts\python.exe'
$accountVault=Join-Path $projectRoot 'exports\private_runtime\schwab_accounts.dpapi'
$receiverProcess=$null
$receiverReady=$false
try {
    if (-not [Environment]::UserInteractive -or [Console]::IsInputRedirected) {
        throw 'Interactive console required'
    }
    Write-Host 'JJTrade AI - conexion de CUENTAS, solo lectura'
    Write-Host 'La app JJTradeAI-Cuenta debe estar Ready For Use.'
    Write-Host 'Callback: https://127.0.0.1:8186/schwab/callback'
    Write-Host 'La simulacion conserva su configuracion. Ordenes reales deshabilitadas.'
    Set-Location -LiteralPath $projectRoot
    if (-not (Test-Path -LiteralPath $accountVault -PathType Leaf)) {
        Write-Host 'Introduce las claves NUEVAS de JJTradeAI-Cuenta; no se muestran al escribir.'
        & $pythonPath (Join-Path $PSScriptRoot 'configure_schwab_accounts_readonly.py')
        if ($LASTEXITCODE -ne 0) {throw 'Configuration not completed'}
    }
    # Validate only the separate profile. Does not refresh tokens or call Schwab.
    & $pythonPath -c 'from real_account_readonly import AccountReadOnlyStore; from scripts.schwab_accounts_oauth_receiver import build_oauth; build_oauth(AccountReadOnlyStore())' 2>$null
    if ($LASTEXITCODE -ne 0) {throw 'Account profile not ready'}
    foreach ($port in @(8186,8187)) {
        $probe=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,$port)
        try {$probe.Start()} finally {$probe.Stop()}
    }
    $receiverScript=Join-Path $PSScriptRoot 'start_schwab_accounts_https.ps1'
    $receiverArgs=@('-NoProfile','-File',('"'+$receiverScript+'"'),'-DurationSeconds','900')
    $receiverProcess=Start-Process -FilePath 'powershell.exe' -ArgumentList $receiverArgs `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    for ($attempt=0;$attempt -lt 30;$attempt++) {
        $receiverProcess.Refresh()
        if ($receiverProcess.HasExited) {throw 'Receiver did not start'}
        try {
            $health=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri 'https://127.0.0.1:8186/schwab/health'
            if ($health.StatusCode -eq 200 -and $health.Content -ceq 'LOCAL_RECEIVER_READY; real_orders_enabled=false; authorization_enabled=true') {
                $receiverReady=$true;break
            }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $receiverReady) {throw 'Local TLS health unavailable'}
    # Visible browser is required for the owner's interactive Schwab consent.
    Start-Process 'https://127.0.0.1:8186/schwab/start'
    Write-Host 'Completa el acceso y la vinculacion en el navegador de ESTA VPS.'
    Write-Host 'Dispones de 15 minutos. Si vence, ejecuta este asistente de nuevo.'
    Write-Host 'Al terminar debe decir: Cuenta autorizada para comprobacion. Ordenes reales deshabilitadas.'
    Write-Host 'No copies la URL de retorno ni claves al chat; comunica solo el resultado.'
} catch {
    if ($receiverProcess -and -not $receiverReady) {
        # Stop only our account receiver; it disposes its own backend in finally.
        New-Item -ItemType File -Path (Join-Path $projectRoot 'exports\private_runtime\schwab_accounts_https.stop') -Force | Out-Null
    }
    Write-Host 'Conexion no completada. Se conserva la configuracion existente y no se enviaron ordenes.'
    Write-Host 'Comprueba el estado de la app, callback y que no haya otro asistente de cuentas abierto.'
    exit 2
}
