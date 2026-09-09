param(
    [ValidateSet("iex", "sip")]
    [string]$Feed = "iex",
    [string]$Symbols = "",
    [int]$Days = 365,
    [ValidateRange(16, 480)]
    [int]$DurationMinutes = 30,
    [string]$Database = "exports\market_data.db",
    [string]$EvidenceOutput = "exports\paper_session_evidence.json"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "venv\Scripts\python.exe"
$sessionExitCode = 1

if ([string]::IsNullOrWhiteSpace($Symbols)) {
    $watchlist = Get-Content -Raw -LiteralPath (Join-Path $projectRoot "config\watchlist.json") | ConvertFrom-Json
    $Symbols = $watchlist.symbols -join ","
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "No existe el Python del entorno virtual: $python"
}

function Read-SecureEnvironmentValue([string]$Prompt) {
    $secureValue = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

$env:ALPACA_API_KEY = Read-SecureEnvironmentValue "Alpaca API key"
$env:ALPACA_API_SECRET = Read-SecureEnvironmentValue "Alpaca API secret"
$env:ALPACA_DATA_FEED = $Feed

try {
    Set-Location -LiteralPath $projectRoot

    Write-Host "Paso 1/3: preflight local seguro"
    & $python "live_strategy_service.py" `
        --symbols $Symbols `
        --days $Days `
        --database $Database `
        --preflight-only
    $preflightExitCode = $LASTEXITCODE

    if ($preflightExitCode -ne 0) {
        $sessionExitCode = $preflightExitCode
        Write-Warning "El preflight local quedo bloqueado; no se inicia el scanner."
    }
    else {
        Write-Host "Paso 2/3: scanner PAPER en primer plano"
        Write-Host "La sesion se detendra automaticamente en $DurationMinutes minutos."
        Write-Host "Parada alternativa desde otra terminal: .\venv\Scripts\python.exe scanner_control.py stop"
        & $python "live_strategy_service.py" `
            --symbols $Symbols `
            --days $Days `
            --database $Database `
            --max-runtime-minutes $DurationMinutes
        $sessionExitCode = $LASTEXITCODE
    }
}
finally {
    Write-Host "Paso 3/3: consolidando evidencia PAPER"
    & $python "paper_session_evidence.py" `
        --database $Database `
        --symbols $Symbols `
        --output $EvidenceOutput
    $evidenceExitCode = $LASTEXITCODE

    Remove-Item Env:ALPACA_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:ALPACA_API_SECRET -ErrorAction SilentlyContinue
    Remove-Item Env:ALPACA_DATA_FEED -ErrorAction SilentlyContinue

    if ($sessionExitCode -eq 0 -and $evidenceExitCode -ne 0) {
        $sessionExitCode = $evidenceExitCode
    }
}

exit $sessionExitCode
