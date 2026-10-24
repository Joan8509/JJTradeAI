# Load an authorized local-paper companion; never touch collector or Windows.
$ErrorActionPreference='Stop'
$practiceRoot=Split-Path -Parent $PSScriptRoot
$practiceEvidence=Join-Path $practiceRoot 'exports\trade_review\connected_manual_deployment'
if(-not (Test-Path -LiteralPath $practiceEvidence)){throw 'Publish/check the private route first'}
$practiceBeforeXml=Export-ScheduledTask -TaskName 'JJTrade-Radar'
if($practiceBeforeXml -match '<Password>'){throw 'Unexpected credential node'}
$practiceBeforeXml | Set-Content -LiteralPath (Join-Path $practiceEvidence 'radar.before.xml') -Encoding UTF8
$practiceTask=Get-ScheduledTask -TaskName 'JJTrade-Radar'
if(-not $practiceTask.Settings.Enabled){throw 'Radar was not enabled; do not activate it implicitly'}
$practiceProcesses=@(Get-CimInstance Win32_Process -Filter "Name='python.exe'")
$practiceCollectorBefore=@($practiceProcesses | Where-Object {$_.CommandLine -match 'vps_private_runtime.*--role\s+collector'} | Select-Object -ExpandProperty ProcessId | Sort-Object)
$practiceRadarBefore=@($practiceProcesses | Where-Object {$_.CommandLine -match 'vps_private_runtime.*--role\s+radar'} | Select-Object -ExpandProperty ProcessId)
if($practiceCollectorBefore.Count -eq 0 -or $practiceRadarBefore.Count -eq 0){throw 'Expected workers missing; investigate first'}
Disable-ScheduledTask -TaskName 'JJTrade-Radar' | Out-Null
try{
    Stop-ScheduledTask -TaskName 'JJTrade-Radar'
    Start-Sleep -Milliseconds 500
    foreach($practicePid in $practiceRadarBefore){
        $practiceRemaining=Get-CimInstance Win32_Process -Filter ('ProcessId='+$practicePid)
        if($practiceRemaining -and $practiceRemaining.CommandLine -match 'vps_private_runtime.*--role\s+radar'){
            Stop-Process -Id $practicePid -ErrorAction Stop
        }
    }
    # Process termination is asynchronous; wait for the recorded old workers
    # before checking that the role is gone. Never target a replacement worker.
    Wait-Process -Id $practiceRadarBefore -Timeout 10 -ErrorAction SilentlyContinue
    if(@(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {$_.CommandLine -match 'vps_private_runtime.*--role\s+radar'}).Count -ne 0){throw 'Old radar still present'}
}finally{
    Enable-ScheduledTask -TaskName 'JJTrade-Radar' | Out-Null
}
Start-ScheduledTask -TaskName 'JJTrade-Radar'
$practiceReady=$null
for($practiceAttempt=0;$practiceAttempt -lt 30;$practiceAttempt++){
    try{
        $practiceStatus=Get-Content -Raw -LiteralPath (Join-Path $practiceRoot 'exports\private_runtime\telegram_manual.status.json') | ConvertFrom-Json
        $practiceAge=([DateTimeOffset]::UtcNow-[DateTimeOffset]::Parse($practiceStatus.heartbeat)).TotalSeconds
        if($practiceStatus.state -eq 'READY' -and $practiceStatus.real_orders_enabled -eq $false -and
            $practiceAge -ge 0 -and $practiceAge -le 10 -and $practiceRadarBefore -notcontains $practiceStatus.pid){
            $practiceReady=$practiceStatus;break
        }
    }catch{}
    Start-Sleep -Seconds 1
}
$practiceAfterXml=Export-ScheduledTask -TaskName 'JJTrade-Radar'
$practiceAfterXml | Set-Content -LiteralPath (Join-Path $practiceEvidence 'radar.after.xml') -Encoding UTF8
if($practiceBeforeXml.Trim() -cne $practiceAfterXml.Trim()){throw 'Task definition changed unexpectedly'}
$practiceCollectorAfter=@(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {$_.CommandLine -match 'vps_private_runtime.*--role\s+collector'} | Select-Object -ExpandProperty ProcessId | Sort-Object)
if(($practiceCollectorBefore -join ',') -cne ($practiceCollectorAfter -join ',')){throw 'Collector process changed; review'}
if($null -eq $practiceReady){throw 'Manual companion not READY; buys remain blocked. Inspect fixed private status.'}
$practiceProcess=Get-CimInstance Win32_Process -Filter ('ProcessId='+$practiceReady.pid)
$practiceOwner=Invoke-CimMethod -InputObject $practiceProcess -MethodName GetOwnerSid
if($practiceProcess.SessionId -ne 0 -or -not $practiceOwner.Sid.EndsWith('-500')){throw 'Unexpected execution identity'}
$practiceServe=Get-Content -Raw -LiteralPath (Join-Path $practiceEvidence 'serve.after.json') | ConvertFrom-Json
$practiceWeb=@($practiceServe.Web.PSObject.Properties)[0]
$practiceOrigin='https://'+$practiceWeb.Name
$practicePage=Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri ($practiceOrigin+'/telegram/')
$practiceHealth=Invoke-RestMethod -TimeoutSec 10 -Uri ($practiceOrigin+'/telegram/health')
$practiceMain=Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri ($practiceOrigin+'/_stcore/health')
if($practiceHealth.status -ne 'LOCAL_SIMULATION' -or $practiceHealth.real_orders_enabled -ne $false -or
    $practicePage.StatusCode -ne 200 -or $practiceMain.StatusCode -ne 200){throw 'HTTPS verification failed'}
$practiceReceipt=[ordered]@{checked_et=(Get-Date).ToString('o');state=$practiceReady.state;pid=$practiceReady.pid;
    administrator_session0=$true;task_definition_preserved=$true;collector_processes_preserved=$true;
    miniapp_https=200;interface_https=200;real_orders_enabled=$false;messages_sent_by_deployment=0}
$practiceReceipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $practiceEvidence 'deployment.json') -Encoding UTF8
$practiceReceipt | ConvertTo-Json
