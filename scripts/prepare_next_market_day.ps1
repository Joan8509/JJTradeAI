param(
    [ValidateSet("iex", "sip")]
    [string]$Feed = "iex",
    [int]$Days = 365
)

$ErrorActionPreference = "Stop"
$runner = Join-Path $PSScriptRoot "run_first_paper_trial.ps1"

Write-Host "Preparacion de las 16 companias para la proxima sesion."
Write-Host "Se descargara o completara el historial y luego la sesion terminara sola."

& $runner `
    -Feed $Feed `
    -Days $Days `
    -DurationMinutes 16 `
    -EvidenceOutput "exports\pre_market_preparation_evidence.json"

exit $LASTEXITCODE

