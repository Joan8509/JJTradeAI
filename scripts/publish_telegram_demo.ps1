$ErrorActionPreference='Stop'
$demoRoot=Split-Path -Parent $PSScriptRoot
$demoPython=Join-Path $demoRoot 'venv\Scripts\python.exe'
$demoTailscale='C:\Program Files\Tailscale\tailscale.exe'
$demoTaskName='JJTrade-DemoVisual'
$demoEvidence=Join-Path $demoRoot ('exports\trade_review\telegram_demo_'+(Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Path $demoEvidence | Out-Null

# Private route identities remain only in ignored local evidence.
$demoBeforeRaw=(& $demoTailscale serve status --json | Out-String)
if($LASTEXITCODE -ne 0){throw 'Serve status unavailable'}
$demoBeforeRaw | Set-Content -LiteralPath (Join-Path $demoEvidence 'serve.before.json') -Encoding UTF8
$demoBefore=$demoBeforeRaw | ConvertFrom-Json
if(@($demoBefore.Web.PSObject.Properties).Count -ne 1){throw 'Review existing HTTPS topology first'}
$demoWebProperty=@($demoBefore.Web.PSObject.Properties)[0]
$demoHost=$demoWebProperty.Name
$demoHandlers=$demoWebProperty.Value.Handlers
if($demoHandlers.'/'.Proxy -ne 'http://127.0.0.1:8501'){throw 'Existing interface mapping not recognized'}
if($demoHandlers.PSObject.Properties.Name -contains '/telegram-demo/'){throw 'Existing demo route requires review'}
if(Get-ScheduledTask -TaskName $demoTaskName -ErrorAction SilentlyContinue){throw 'Existing demo task requires review'}
$demoOrigin='https://'+$demoHost
$demoBeforeHealth=Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri ($demoOrigin+'/_stcore/health')
if($demoBeforeHealth.StatusCode -ne 200){throw 'Interface unavailable before demo'}
$demoAction=New-ScheduledTaskAction -Execute $demoPython -Argument ('"'+(Join-Path $demoRoot 'scripts\serve_telegram_demo.py')+'"') -WorkingDirectory $demoRoot
# Static server never reads DPAPI. SYSTEM avoids any password or RDP dependency.
$demoPrincipal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Limited
$demoSettings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 24) -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $demoTaskName -Action $demoAction -Principal $demoPrincipal -Settings $demoSettings -Description 'Temporary read-only visual demo; no trading APIs or credentials; maximum 24h, no startup trigger.' | Out-Null
Export-ScheduledTask -TaskName $demoTaskName | Set-Content -LiteralPath (Join-Path $demoEvidence 'demo.task.xml') -Encoding UTF8
Start-ScheduledTask -TaskName $demoTaskName
$demoLocalReady=$false
for($demoAttempt=0;$demoAttempt -lt 12;$demoAttempt++){
    try{
        $demoHealth=Invoke-RestMethod -TimeoutSec 2 -Uri 'http://127.0.0.1:8185/health'
        if($demoHealth.mode -eq 'DEMO_VISUAL_ONLY' -and $demoHealth.real_orders_enabled -eq $false -and $demoHealth.simulation_orders_enabled -eq $false){$demoLocalReady=$true;break}
    }catch{Start-Sleep -Milliseconds 500}
}
if(-not $demoLocalReady){throw 'Demo loopback health unavailable; existing Serve mapping unchanged'}
# Add only this path; never reset Serve, remove '/', or enable Funnel.
$demoServeOutput=(& $demoTailscale serve --bg --set-path=/telegram-demo/ http://127.0.0.1:8185 2>&1 | Out-String)
$demoServeOutput | Set-Content -LiteralPath (Join-Path $demoEvidence 'serve.change.txt') -Encoding UTF8
if($LASTEXITCODE -ne 0){throw 'Demo route installation failed'}
$demoAfterRaw=(& $demoTailscale serve status --json | Out-String)
$demoAfterRaw | Set-Content -LiteralPath (Join-Path $demoEvidence 'serve.after.json') -Encoding UTF8
$demoAfter=$demoAfterRaw | ConvertFrom-Json
$demoAfterHandlers=@($demoAfter.Web.PSObject.Properties)[0].Value.Handlers
foreach($demoOldHandler in $demoHandlers.PSObject.Properties){
    $demoOldJson=$demoOldHandler.Value | ConvertTo-Json -Compress -Depth 10
    $demoCurrentJson=$demoAfterHandlers.($demoOldHandler.Name) | ConvertTo-Json -Compress -Depth 10
    if($demoOldJson -cne $demoCurrentJson){throw 'Previous route changed unexpectedly; review private snapshot'}
}
$demoPublic=Invoke-RestMethod -TimeoutSec 10 -Uri ($demoOrigin+'/telegram-demo/health')
$demoPage=Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri ($demoOrigin+'/telegram-demo/')
$demoAfterHealth=Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri ($demoOrigin+'/_stcore/health')
if($demoPublic.mode -ne 'DEMO_VISUAL_ONLY' -or $demoPage.StatusCode -ne 200 -or $demoAfterHealth.StatusCode -ne 200){throw 'HTTPS verification failed'}
$demoReceipt=[ordered]@{checked_et=(Get-Date).ToString('o');url=($demoOrigin+'/telegram-demo/');evidence=$demoEvidence;task=$demoTaskName;existing_routes_preserved=$true;demo_https=200;interface_https=200;real_orders_enabled=$false;simulation_orders_enabled=$false;telegram_sent=$false;maximum_runtime_hours=24}
$demoReceipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $demoEvidence 'deployment.json') -Encoding UTF8
$demoReceipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $demoRoot 'exports\trade_review\telegram_demo_current.json') -Encoding UTF8
[pscustomobject]@{DemoHTTPS=200;InterfaceHTTPS=200;PreviousRoutesPreserved=$true;RealOrdersEnabled=$false;SimulationOrdersEnabled=$false;TemporaryTask=$demoTaskName} | ConvertTo-Json
