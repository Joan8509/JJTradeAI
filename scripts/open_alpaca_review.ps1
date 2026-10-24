$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
& (Join-Path $projectRoot 'venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'review_alpaca_credentials.py')
$resultCode = $LASTEXITCODE
Write-Host ('Resultado de revision: ' + $resultCode)
$null = Read-Host 'Pulsa Enter para cerrar esta ventana'
exit $resultCode
