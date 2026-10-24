$ErrorActionPreference='Stop'
$practiceRoot=Split-Path -Parent $PSScriptRoot
$practiceTailscale='C:\Program Files\Tailscale\tailscale.exe'
$practiceEvidence=Join-Path $practiceRoot 'exports\trade_review\connected_manual_deployment'
New-Item -ItemType Directory -Path $practiceEvidence -Force | Out-Null
$practiceRaw=(& $practiceTailscale serve status --json | Out-String)
if($LASTEXITCODE -ne 0){throw 'Serve unavailable'}
$practiceRaw | Set-Content -LiteralPath (Join-Path $practiceEvidence 'serve.before.json') -Encoding UTF8
$practiceBefore=$practiceRaw | ConvertFrom-Json
if(@($practiceBefore.Web.PSObject.Properties).Count -ne 1){throw 'Unexpected HTTPS topology'}
$practiceWeb=@($practiceBefore.Web.PSObject.Properties)[0]
$practiceHandlers=$practiceWeb.Value.Handlers
if($practiceHandlers.'/'.Proxy -ne 'http://127.0.0.1:8501'){throw 'Main interface mapping changed'}
if($practiceHandlers.PSObject.Properties.Name -contains '/telegram/'){
    if($practiceHandlers.'/telegram/'.Proxy -ne 'http://127.0.0.1:8184'){throw 'Review conflicting route'}
}else{
    # Only a new path. Never reset Serve, replace the main app or enable Funnel.
    $practiceChange=(& $practiceTailscale serve --bg --set-path=/telegram/ http://127.0.0.1:8184 2>&1 | Out-String)
    $practiceChange | Set-Content -LiteralPath (Join-Path $practiceEvidence 'serve.change.txt') -Encoding UTF8
    if($LASTEXITCODE -ne 0){throw 'Serve change failed'}
}
$practiceAfterRaw=(& $practiceTailscale serve status --json | Out-String)
$practiceAfterRaw | Set-Content -LiteralPath (Join-Path $practiceEvidence 'serve.after.json') -Encoding UTF8
$practiceAfter=$practiceAfterRaw | ConvertFrom-Json
$practiceAfterHandlers=@($practiceAfter.Web.PSObject.Properties)[0].Value.Handlers
foreach($practiceOld in $practiceHandlers.PSObject.Properties){
    if(($practiceOld.Value | ConvertTo-Json -Compress -Depth 10) -cne
        ($practiceAfterHandlers.($practiceOld.Name) | ConvertTo-Json -Compress -Depth 10)){
        throw 'Previous route changed unexpectedly'
    }
}
$practiceOrigin='https://'+$practiceWeb.Name
$practiceMain=Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri ($practiceOrigin+'/_stcore/health')
if($practiceMain.StatusCode -ne 200){throw 'Main app HTTPS unavailable'}
[pscustomobject]@{InterfaceHTTPS=200;ExistingRoutesPreserved=$true;LocalManualRoutePrepared=$true;RealOrdersEnabled=$false;MessagesSent=0} | ConvertTo-Json
