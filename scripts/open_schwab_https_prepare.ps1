# User-visible certificate consent; no brokerage credentials in this window.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$result = 2
try {
    Write-Host 'JJTrade AI - preparacion HTTPS LOCAL (sin claves de Schwab)'
    Write-Host ''
    Write-Host 'Windows puede pedir confirmar el certificado:'
    Write-Host '  JJTrade AI Schwab Loopback'
    Write-Host 'Solo sirve para 127.0.0.1 en esta VPS. La clave privada no se exporta.'
    Write-Host 'Se confia solo bajo el usuario Administrator, no en la PC ni en otros usuarios.'
    Write-Host 'Si aparece esa advertencia, revisa el nombre y confirma para continuar.'
    Write-Host 'No aceptes certificados de otro nombre. No introduzcas claves aqui.'
    Write-Host ''
    & (Join-Path $PSScriptRoot 'start_schwab_local_https.ps1') -PrepareCertificate -CertificateOnly
    if (-not $?) { throw 'Certificate preparation did not complete' }
    & (Join-Path $PSScriptRoot 'test_schwab_local_https.ps1')
    if (-not $?) { throw 'Local TLS verification did not complete' }
    $result = 0
    Write-Host ''
    Write-Host 'HTTPS local verificado. El listener de prueba se ha cerrado.'
} catch {
    Write-Host 'La preparacion HTTPS no se completo. Comunica solo este estado, sin claves.'
} finally {
    [pscustomobject]@{checked_utc=[DateTime]::UtcNow.ToString('o');result=$result;
        real_orders_enabled=$false;schwab_api_calls=0} | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $root 'exports\private_runtime\schwab_https_setup.json') -Encoding UTF8
}
Write-Host ''
Write-Host 'Este paso no autoriza Schwab, no conecta paperMoney ni envia ordenes.'
$null = Read-Host 'Pulsa Enter para cerrar'
exit $result
