param([switch]$HealthOnly,[ValidateRange(10,3600)][int]$DurationSeconds=900)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$privateRoot=Join-Path $projectRoot 'exports\private_runtime'
$stopPath=Join-Path $privateRoot 'schwab_accounts_https.stop'
$backend=$null
try {
    if (-not ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value.EndsWith('-500'))) {throw 'Owner required'}
    if (-not (Test-Path -LiteralPath $privateRoot -PathType Container)) {throw 'Private directory required'}
    # Different ports, stop file, backend and status from the market-data receiver.
    foreach ($port in @(8186,8187)) {
        $probe=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,$port)
        try {$probe.Start()} finally {$probe.Stop()}
    }
    $certificates=@(Get-ChildItem Cert:\CurrentUser\My | Where-Object {$_.FriendlyName -eq 'JJTrade AI Schwab Loopback TLS'})
    if ($certificates.Count -ne 1) {throw 'Existing loopback certificate required'}
    $certificate=$certificates[0]
    if (-not $certificate.HasPrivateKey -or $certificate.NotAfter -lt (Get-Date).AddDays(1) -or
        $certificate.NotBefore -gt (Get-Date) -or $certificate.Subject -ne 'CN=JJTrade AI Schwab Loopback' -or
        $certificate.Subject -ne $certificate.Issuer) {throw 'Usable certificate required'}
    $san=$certificate.Extensions | Where-Object {$_.Oid.Value -eq '2.5.29.17'}
    $eku=$certificate.Extensions | Where-Object {$_.Oid.Value -eq '2.5.29.37'}
    $constraints=$certificate.Extensions | Where-Object {$_.Oid.Value -eq '2.5.29.19'}
    if (-not $san -or [BitConverter]::ToString($san.RawData) -ne '30-06-87-04-7F-00-00-01' -or
        -not $eku -or $eku.EnhancedKeyUsages.Count -ne 1 -or
        $eku.EnhancedKeyUsages[0].Value -ne '1.3.6.1.5.5.7.3.1' -or
        -not $constraints -or $constraints.CertificateAuthority) {throw 'Exact loopback server certificate required'}
    $rsa=[Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($certificate)
    try {
        if ($rsa -isnot [Security.Cryptography.RSACng] -or $rsa.Key.ExportPolicy -ne 'None') {throw 'Nonexportable key required'}
    } finally {if ($rsa) {$rsa.Dispose()}}
    $trusted=@(Get-ChildItem Cert:\CurrentUser\Root | Where-Object {$_.Thumbprint -eq $certificate.Thumbprint})
    if ($trusted.Count -ne 1) {throw 'Existing trusted certificate required'}
    # No certificate creation/import or data-app reconfiguration here.
    Add-Type -Path (Join-Path $PSScriptRoot 'schwab_accounts_loopback_tls.cs')
    if (Test-Path -LiteralPath $stopPath) {Remove-Item -LiteralPath $stopPath}
    $pythonPath=Join-Path $projectRoot 'venv\Scripts\python.exe'
    $arguments=@('-u',('"'+(Join-Path $PSScriptRoot 'schwab_accounts_oauth_receiver.py')+'"'))
    if ($HealthOnly) {$arguments+='--health-only'}
    $backend=Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    Start-Sleep -Milliseconds 600
    if ($backend.HasExited) {throw 'Backend unavailable'}
    $receipt=@{state='STARTING';checked_at=[DateTime]::UtcNow.ToString('o');pid=$PID;
        callback='https://127.0.0.1:8186/schwab/callback';health_only=[bool]$HealthOnly;real_orders_enabled=$false}
    $receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $privateRoot 'schwab_accounts_https.runtime.json') -Encoding UTF8
    [JJSchwabAccountsLoopbackTls]::Run($certificate,$stopPath,$DurationSeconds)
} catch {
    @{state='ACCOUNT_RECEIVER_UNAVAILABLE';real_orders_enabled=$false;error_type=$_.Exception.GetType().Name}|ConvertTo-Json -Compress
    exit 2
} finally {
    if ($backend -and -not $backend.HasExited) {& taskkill.exe /PID $backend.Id /T /F *> $null}
    if ($receipt) {
        $receipt.state='STOPPED';$receipt.checked_at=[DateTime]::UtcNow.ToString('o')
        $receipt|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $privateRoot 'schwab_accounts_https.runtime.json') -Encoding UTF8
    }
}
