param(
    [switch]$PrepareCertificate,
    [switch]$CertificateOnly,
    [switch]$HealthOnly,
    [ValidateRange(10,3600)][int]$DurationSeconds = 900
)
$ErrorActionPreference = 'Stop'
$stage = 'identity'
$backend = $null
$trustExit = $null
$projectRoot = Split-Path -Parent $PSScriptRoot
$privateRoot = Join-Path $projectRoot 'exports\private_runtime'
$stopPath = Join-Path $privateRoot 'schwab_https.stop'
try {
    $ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if (-not $ownerSid.EndsWith('-500')) { throw 'Administrator required' }
    if (-not (Test-Path -LiteralPath $privateRoot -PathType Container)) { throw 'Private directory required' }
    $stage = 'port_check'
    foreach ($port in @(8182,8183)) {
        $probe = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,$port)
        try { $probe.Start() } finally { $probe.Stop() }
    }
    if (Test-Path -LiteralPath $stopPath) { Remove-Item -LiteralPath $stopPath }
    $stage = 'certificate'
    $friendly = 'JJTrade AI Schwab Loopback TLS'
    $certificates = @(Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.FriendlyName -eq $friendly })
    if ($certificates.Count -eq 0 -and $PrepareCertificate) {
        $certificateOptions = @{
            Type = 'Custom'; Subject = 'CN=JJTrade AI Schwab Loopback'
            FriendlyName = $friendly; CertStoreLocation = 'Cert:\CurrentUser\My'
            KeyAlgorithm = 'RSA'; KeyLength = 2048; HashAlgorithm = 'SHA256'
            KeyExportPolicy = 'NonExportable'; KeyUsage = @('DigitalSignature','KeyEncipherment')
            NotAfter = (Get-Date).AddYears(1)
            TextExtension = @('2.5.29.17={text}IPAddress=127.0.0.1',
                '2.5.29.37={text}1.3.6.1.5.5.7.3.1','2.5.29.19={text}ca=0')
        }
        $certificates = @(New-SelfSignedCertificate @certificateOptions)
    }
    if ($certificates.Count -ne 1) { throw 'Review existing certificates' }
    $certificate = $certificates[0]
    if (-not $certificate.HasPrivateKey -or $certificate.NotAfter -lt (Get-Date).AddDays(1) -or
        $certificate.NotBefore -gt (Get-Date) -or $certificate.Subject -ne 'CN=JJTrade AI Schwab Loopback' -or
        $certificate.Subject -ne $certificate.Issuer) {
        throw 'Usable certificate required'
    }
    $san = $certificate.Extensions | Where-Object {$_.Oid.Value -eq '2.5.29.17'}
    $eku = $certificate.Extensions | Where-Object {$_.Oid.Value -eq '2.5.29.37'}
    $constraints = $certificate.Extensions | Where-Object {$_.Oid.Value -eq '2.5.29.19'}
    if (-not $san -or [BitConverter]::ToString($san.RawData) -ne '30-06-87-04-7F-00-00-01' -or
        -not $eku -or $eku.EnhancedKeyUsages.Count -ne 1 -or
        $eku.EnhancedKeyUsages[0].Value -ne '1.3.6.1.5.5.7.3.1' -or
        -not $constraints -or $constraints.CertificateAuthority) {
        throw 'Exact loopback-only server certificate required'
    }
    $rsa = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($certificate)
    try {
        if ($rsa -isnot [Security.Cryptography.RSACng] -or $rsa.Key.ExportPolicy -ne 'None') {
            throw 'Nonexportable Windows key required'
        }
    } finally { if ($rsa) { $rsa.Dispose() } }
    $stage = 'trust'
    $rootStore = New-Object Security.Cryptography.X509Certificates.X509Store('Root','CurrentUser')
    $rootStore.Open('ReadOnly')
    $alreadyTrusted = $false
    try {
        $found = $rootStore.Certificates.Find('FindByThumbprint',$certificate.Thumbprint,$false)
        $alreadyTrusted = $found.Count -eq 1
    } finally { $rootStore.Close() }
    if (-not $alreadyTrusted) {
        if (-not $PrepareCertificate) { throw 'Prepare trust first' }
        # certutil's supported import avoids an unattended .NET root-store dialog.
        # RawData is the PUBLIC certificate only. Its CNG private key never leaves Windows.
        $publicPath = Join-Path $privateRoot 'schwab_loopback_public.cer'
        [IO.File]::WriteAllBytes($publicPath,$certificate.RawData)
        $stage = 'trust_import'
        & certutil.exe -user -f -addstore Root $publicPath *> $null
        $trustExit = $LASTEXITCODE
        if ($LASTEXITCODE -ne 0) { throw 'Public certificate import failed' }
        $trusted = @(Get-ChildItem Cert:\CurrentUser\Root | Where-Object {$_.Thumbprint -eq $certificate.Thumbprint})
        if ($trusted.Count -ne 1) { throw 'Certificate trust not confirmed' }
    }
    if ($CertificateOnly) {
        [pscustomobject]@{status='LOCAL_CERTIFICATE_READY';private_key_exported=$false;real_orders_enabled=$false} | ConvertTo-Json -Compress
        return
    }
    $stage = 'compile'
    Add-Type -Path (Join-Path $PSScriptRoot 'schwab_loopback_tls.cs')
    $stage = 'backend'
    $pythonPath = Join-Path $projectRoot 'venv\Scripts\python.exe'
    $arguments = @('-u',('"'+(Join-Path $PSScriptRoot 'schwab_oauth_receiver.py')+'"'))
    if ($HealthOnly) { $arguments += '--health-only' }
    $backend = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    Start-Sleep -Milliseconds 600
    if ($backend.HasExited) { throw 'Backend unavailable' }
    $receipt = [ordered]@{
        state='LOCAL_LISTENER_STARTING'; updated_utc=[DateTime]::UtcNow.ToString('o')
        pid=$PID; backend_launcher_pid=$backend.Id; health_only=[bool]$HealthOnly
        callback='https://127.0.0.1:8182/schwab/callback'; real_orders_enabled=$false
        certificate_thumbprint=$certificate.Thumbprint; private_key_exported=$false
        certificate_trusted_current_user=$true; listener_address='127.0.0.1'
        last_failure_stage=$null; last_failure_code=0
    }
    $receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $privateRoot 'schwab_https.runtime.json') -Encoding UTF8
    $stage = 'serve'
    [JJSchwabLoopbackTls]::Run($certificate,$stopPath,$DurationSeconds)
} catch {
    [pscustomobject]@{status='SCHWAB_HTTPS_UNAVAILABLE';stage=$stage;error_type=$_.Exception.GetType().Name;
        error_code=$_.Exception.HResult;trust_exit=$trustExit;real_orders_enabled=$false} | ConvertTo-Json -Compress
    exit 2
} finally {
    if ($backend -and -not $backend.HasExited) {
        # Only the process tree spawned here; venv launcher has a Python child.
        & taskkill.exe /PID $backend.Id /T /F *> $null
    }
    if (Test-Path -LiteralPath (Join-Path $privateRoot 'schwab_https.runtime.json')) {
        $receipt = Get-Content -Raw -LiteralPath (Join-Path $privateRoot 'schwab_https.runtime.json') | ConvertFrom-Json
        if ($receipt.pid -eq $PID) {
            $receipt.state='STOPPED'; $receipt.updated_utc=[DateTime]::UtcNow.ToString('o')
            $receipt.last_failure_stage=[JJSchwabLoopbackTls]::LastFailureStage
            $receipt.last_failure_code=[JJSchwabLoopbackTls]::LastFailureCode
            $receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $privateRoot 'schwab_https.runtime.json') -Encoding UTF8
        }
    }
}
