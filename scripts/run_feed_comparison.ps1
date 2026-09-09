param(
    [string]$Symbols = "SPY,QQQ",
    [ValidateRange(30, 730)]
    [int]$Days = 365,
    [ValidateRange(1, 30)]
    [int]$ReplaySessions = 5,
    [string]$Output = "exports\feed_comparison.json"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "venv\Scripts\python.exe"

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

try {
    Set-Location -LiteralPath $projectRoot
    & $python "feed_comparison.py" --symbols $Symbols --days $Days --replay-sessions $ReplaySessions --output $Output
    exit $LASTEXITCODE
}
finally {
    Remove-Item Env:ALPACA_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:ALPACA_API_SECRET -ErrorAction SilentlyContinue
}
