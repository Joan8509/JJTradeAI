# Deliberately interactive: secrets only through Python getpass, never argv/logs.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
Write-Host 'JJTrade AI - configuracion privada de DATOS Schwab'
Write-Host 'No inicia autorizacion web, no conecta cuentas ni envia ordenes.'
Write-Host 'Introduce Client ID y Client Secret aqui. La entrada no muestra caracteres.'
Write-Host 'No pegues esos valores en el chat ni tomes capturas con claves visibles.'
Write-Host ''
& (Join-Path $root 'venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'configure_schwab_readonly.py') --market-data
$setupResult = $LASTEXITCODE
Write-Host ''
Write-Host ('Resultado: '+$setupResult+'. Si es 0, la configuracion quedo cifrada bajo Administrator.')
Write-Host 'Este paso no inicia sesion en Schwab. Las ordenes reales siguen deshabilitadas.'
$null = Read-Host 'Pulsa Enter para cerrar'
exit $setupResult
