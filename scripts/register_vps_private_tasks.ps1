$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot 'venv\Scripts\python.exe'
$runner = Join-Path $projectRoot 'vps_private_runtime.py'
$privateDirectory = Join-Path $projectRoot 'exports\private_runtime'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$taskNames = @('JJTrade-Colector', 'JJTrade-Radar', 'JJTrade-Colector-Verificar', 'JJTrade-Radar-Verificar')
$folder = $null
$touched = @()
try {
    if (-not $identity.User.Value.EndsWith('-500')) { throw 'Identity mismatch' }
    # Read only from the anonymous pipe supplied by the interactive helper.
    $inputData = [Console]::In.ReadToEnd() | ConvertFrom-Json
    if ([string]::IsNullOrEmpty($inputData.password) -or $inputData.probe_id -notmatch '^[a-f0-9]{32}$') { throw 'Invalid input' }
    $scheduler = New-Object -ComObject 'Schedule.Service'
    $scheduler.Connect()
    $folder = $scheduler.GetFolder('\')
    foreach ($name in $taskNames) {
        $existing = $null
        try { $existing = $folder.GetTask($name) } catch {}
        if ($existing -and ($existing.State -eq 4 -or $existing.Definition.Actions.Item(1).Path -ne $python)) {
            throw 'Existing task is running or has a different action'
        }
    }
    foreach ($name in $taskNames) {
        $isProbe = $name.EndsWith('-Verificar')
        $role = if ($name -like '*Colector*') { 'collector' } else { 'radar' }
        $definition = $scheduler.NewTask(0)
        $definition.RegistrationInfo.Description = 'JJTrade: CurrentUser DPAPI, pending coordinated cutover; no real orders.'
        $definition.Principal.UserId = $identity.User.Value
        $definition.Principal.LogonType = 1 # TASK_LOGON_PASSWORD; never S4U or InteractiveToken.
        $definition.Principal.RunLevel = 1
        $definition.Settings.Enabled = $false
        $definition.Settings.MultipleInstances = 2 # IgnoreNew
        $definition.Settings.ExecutionTimeLimit = 'PT0S'
        $definition.Settings.StartWhenAvailable = $true
        $definition.Settings.DisallowStartIfOnBatteries = $false
        $definition.Settings.StopIfGoingOnBatteries = $false
        $definition.Settings.AllowDemandStart = $true
        if (-not $isProbe) {
            $definition.Settings.RestartCount = 3
            $definition.Settings.RestartInterval = 'PT1M'
            $boot = $definition.Triggers.Create(8)
            $boot.Enabled = $true
            $boot.Delay = 'PT30S'
            $timer = $definition.Triggers.Create(1)
            $timer.StartBoundary = (Get-Date).AddMinutes(1).ToString('yyyy-MM-ddTHH:mm:ss')
            $timer.Enabled = $true
            $timer.Repetition.Interval = 'PT1M'
            $timer.Repetition.StopAtDurationEnd = $false
        }
        $action = $definition.Actions.Create(0)
        $action.Path = $python
        $action.WorkingDirectory = $projectRoot
        $action.Arguments = '"' + $runner + '" --role ' + $role
        if ($isProbe) { $action.Arguments += ' --check --probe-id ' + $inputData.probe_id }
        $registered = $folder.RegisterTaskDefinition($name, $definition, 6, $identity.User.Value, $inputData.password, 1, $null)
        $touched += $name
        $registered.Enabled = $false
    }
    # Only the --check tasks are ever enabled/run. Production remains disabled.
    foreach ($name in @('JJTrade-Colector-Verificar', 'JJTrade-Radar-Verificar')) {
        $task = $folder.GetTask($name)
        $role = if ($name -like '*Colector*') { 'collector' } else { 'radar' }
        $task.Enabled = $true
        $instance = $task.Run($null)
        $deadline = (Get-Date).AddSeconds(60)
        $completed = $false
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 1
            $receipt = Join-Path $privateDirectory ($role + '.probe.json')
            if (Test-Path -LiteralPath $receipt) {
                $data = Get-Content -Raw -LiteralPath $receipt | ConvertFrom-Json
                $fresh = $data.probe_id -eq $inputData.probe_id
                $task = $folder.GetTask($name)
                if ($fresh -and $task.State -ne 4) {
                    $completed = $data.status -eq 'LOCAL_ACCESS_OK' -and $data.session_id -eq 0 -and $task.LastTaskResult -eq 0
                    break
                }
            }
        }
        $task.Enabled = $false
        if (-not $completed) { throw 'Offline batch validation failed' }
    }
    exit 0
}
catch { exit 1 }
finally {
    if ($folder) {
        foreach ($name in $touched) {
            try {
                $task = $folder.GetTask($name)
                $task.Enabled = $false
                if ($name.EndsWith('-Verificar') -and $task.State -eq 4) { $task.Stop(0) }
            } catch {}
        }
    }
    if ($inputData) { $inputData.password = $null }
}
