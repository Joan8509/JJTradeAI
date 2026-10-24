$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
& (Join-Path $projectRoot 'venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'configure_vps_private.py')
$resultCode = $LASTEXITCODE
Write-Host ('Resultado de configuracion: ' + $resultCode)
$null = Read-Host 'Pulsa Enter para cerrar esta ventana'
exit $resultCode
