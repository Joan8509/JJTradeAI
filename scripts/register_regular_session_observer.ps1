param([switch]$Register)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$taskName = 'JJTrade-Observacion-RTH'
$python = Join-Path $projectRoot 'venv\Scripts\python.exe'
$observer = Join-Path $projectRoot 'scripts\observe_regular_session.py'
if (-not $Register) {
    [pscustomobject]@{Task=$taskName;Identity='SYSTEM';Schedule='Daily 09:25-16:10 ET and 30 minutes after startup, every minute';DatabaseAccess='ReadOnly';Network=$false;ActivationSupported=$false} | ConvertTo-Json
    exit 0
}
if ([TimeZoneInfo]::Local.Id -ne 'Eastern Standard Time') { throw 'Expected Eastern Windows timezone' }
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $observer)) { throw 'Missing observer' }
$radar = Get-ScheduledTask -TaskName 'JJTrade-Radar'
if ($radar.Settings.Enabled -or $radar.State -eq 'Running') { throw 'Radar must remain disabled' }
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) { throw 'Observer already registered: review rather than overwrite' }
$action = New-ScheduledTaskAction -Execute $python -Argument ('"'+$observer+'"') -WorkingDirectory $projectRoot
$daily = New-ScheduledTaskTrigger -Daily -At '09:25'
$repetition = New-ScheduledTaskTrigger -Once -At '09:25' -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Hours 6 -Minutes 45)
$daily.Repetition = $repetition.Repetition
$boot = New-ScheduledTaskTrigger -AtStartup
$boot.Delay = 'PT45S'
$bootRepeat = New-ScheduledTaskTrigger -Once -At '09:25' -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Minutes 30)
$boot.Repetition = $bootRepeat.Repetition
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Seconds 45) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($daily,$boot) -Principal $principal -Settings $settings -Description 'Passive RTH evidence only: read-only SQLite; no credentials, API, messages, orders or radar activation.' | Select-Object TaskName,State
