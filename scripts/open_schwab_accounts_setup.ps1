# Run interactively as Administrator in the VPS. Secrets are hidden by getpass.
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
Write-Host 'JJTrade AI - aplicacion SEPARADA de cuentas (solo lectura)'
Write-Host 'Usa las claves de JJTradeAI-Cuenta, no las de JJTradeAI-Datos.'
Write-Host 'No copies claves al chat. Este paso no modifica la simulacion.'
& (Join-Path $root 'venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'configure_schwab_accounts_readonly.py')
$result=$LASTEXITCODE
Write-Host ''
if ($result -eq 0) {Write-Host 'Siguiente paso: autorizar la nueva aplicacion en el navegador de la VPS.'}
$null=Read-Host 'Pulsa Enter para cerrar'
exit $result
