param([switch]$ReloadObserver)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot 'venv\Scripts\python.exe'
$observerPath = Join-Path $projectRoot 'scripts\observe_movement_strength.py'
$taskName = 'JJTrade-ObservacionFuerza'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$scheduler = New-Object -ComObject 'Schedule.Service'
$scheduler.Connect()
$folder = $scheduler.GetFolder('\')
$prior = $null
try { $prior = $folder.GetTask($taskName) } catch {}
if ($prior) {
    if ($prior.Definition.Actions.Item(1).Path -ne $pythonPath -or
        $prior.Definition.Actions.Item(1).Arguments -ne ('"' + $observerPath + '"')) {
        throw 'Existing observer task has another action; preserved without changes.'
    }
    $task = $prior
    if ($ReloadObserver -and $task.State -eq 4) {
        # Only this independent research task, after checking its exact action.
        $task.Stop(0)
        for ($attempt = 0; $attempt -lt 40 -and $task.State -eq 4; $attempt++) {
            Start-Sleep -Milliseconds 100
        }
        if ($task.State -eq 4) { throw 'Observer did not stop; no other process will be touched.' }
    }
} else {
    $definition = $scheduler.NewTask(0)
    $definition.RegistrationInfo.Description = 'Read-only local tick research. No broker, alerts, credentials, or production state writes.'
    $definition.Principal.UserId = $identity.User.Value
    # S4U intentionally applies ONLY to this local research task: no network/DPAPI.
    $definition.Principal.LogonType = 2
    $definition.Principal.RunLevel = 0
    $definition.Settings.Enabled = $true
    $definition.Settings.MultipleInstances = 2
    $definition.Settings.ExecutionTimeLimit = 'PT0S'
    $definition.Settings.Priority = 7
    $definition.Settings.StartWhenAvailable = $true
    $definition.Settings.DisallowStartIfOnBatteries = $false
    $definition.Settings.StopIfGoingOnBatteries = $false
    $definition.Settings.RestartCount = 3
    $definition.Settings.RestartInterval = 'PT1M'
    $boot = $definition.Triggers.Create(8)
    $boot.Delay = 'PT1M'
    $boot.Enabled = $true
    $timer = $definition.Triggers.Create(1)
    $timer.StartBoundary = (Get-Date).AddMinutes(1).ToString('yyyy-MM-ddTHH:mm:ss')
    $timer.Repetition.Interval = 'PT1M'
    $timer.Repetition.StopAtDurationEnd = $false
    $timer.Enabled = $true
    $action = $definition.Actions.Create(0)
    $action.Path = $pythonPath
    $action.Arguments = '"' + $observerPath + '"'
    $action.WorkingDirectory = $projectRoot
    $task = $folder.RegisterTaskDefinition($taskName, $definition, 2, $identity.User.Value, $null, 2, $null)
}
if ($task.State -ne 4) { $null = $task.Run($null) }
[pscustomobject]@{Task=$taskName; State=$task.State; Mode='OBSERVATION_ONLY'; ProductionTasksChanged=$false} | ConvertTo-Json
