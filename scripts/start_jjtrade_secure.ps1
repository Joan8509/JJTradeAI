param(
    [ValidateSet("iex", "sip")]
    [string]$Feed = "iex",
    [string]$Symbols = "",
    [int]$Days = 365,
    [int]$Port = 8501,
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "venv\Scripts\python.exe"

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
    if ($PreflightOnly) {
        & $python "live_strategy_service.py" --symbols $Symbols --days $Days --preflight-only
        exit $LASTEXITCODE
    }
    & $python -m streamlit run "app.py" --server.port $Port
    exit $LASTEXITCODE
}
finally {
    Remove-Item Env:ALPACA_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:ALPACA_API_SECRET -ErrorAction SilentlyContinue
    Remove-Item Env:ALPACA_DATA_FEED -ErrorAction SilentlyContinue
}
