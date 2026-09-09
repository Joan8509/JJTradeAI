param(
    [ValidateSet("iex", "sip")]
    [string]$Feed = "iex",
    [int]$Days = 365,
    [ValidateRange(16, 480)]
    [int]$DurationMinutes = 420
)

$ErrorActionPreference = "Stop"
$runner = Join-Path $PSScriptRoot "run_first_paper_trial.ps1"

Write-Host "JJTrade AI: jornada PAPER con la lista completa de 16 companias."
Write-Host "Duracion programada: $DurationMinutes minutos."

& $runner `
    -Feed $Feed `
    -Days $Days `
    -DurationMinutes $DurationMinutes `
    -EvidenceOutput "exports\market_day_evidence.json"

exit $LASTEXITCODE

