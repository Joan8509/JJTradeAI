param([switch]$Register,[switch]$PromptCredential)
$ErrorActionPreference='Stop'
$authRoot=Split-Path -Parent $PSScriptRoot
$authName='JJTrade-Schwab-Autorizacion'
if(-not $Register){
 [pscustomobject]@{Task=$authName;Interval='PT5M';Identity='Administrator';LogonType='Password';RealOrdersEnabled=$false;OtherServicesRestarted=$false}|ConvertTo-Json
 exit 0
}
$authIdentity=[Security.Principal.WindowsIdentity]::GetCurrent()
if(-not $authIdentity.User.Value.EndsWith('-500')){throw 'Administrator required'}
$authService=New-Object -ComObject 'Schedule.Service'
$authService.Connect()
$authFolder=$authService.GetFolder('\')
$authExisting=$null
try{$authExisting=$authFolder.GetTask($authName)}catch{}
if($authExisting){throw 'Existing task must be reviewed; not overwritten'}
$authDefinition=$authService.NewTask(0)
$authDefinition.RegistrationInfo.Description='Independent Schwab OAuth maintenance and read-only premarket check; operational notices only; no trading or strategy access.'
$authDefinition.Principal.UserId=$authIdentity.User.Value
$authDefinition.Principal.LogonType=1
$authDefinition.Principal.RunLevel=1
$authDefinition.Settings.Enabled=$false
$authDefinition.Settings.MultipleInstances=2
$authDefinition.Settings.ExecutionTimeLimit='PT2M'
$authDefinition.Settings.StartWhenAvailable=$true
$authDefinition.Settings.DisallowStartIfOnBatteries=$false
$authDefinition.Settings.StopIfGoingOnBatteries=$false
$authDefinition.Settings.AllowDemandStart=$true
$authTimer=$authDefinition.Triggers.Create(1)
$authNext=(Get-Date).AddMinutes(5)
$authNext=$authNext.Date.AddHours($authNext.Hour).AddMinutes(5*[math]::Floor($authNext.Minute/5))
$authTimer.StartBoundary=$authNext.ToString('yyyy-MM-ddTHH:mm:ss')
$authTimer.Repetition.Interval='PT5M'
$authTimer.Repetition.StopAtDurationEnd=$false
$authTimer.Enabled=$true
$authBoot=$authDefinition.Triggers.Create(8)
$authBoot.Delay='PT45S'
$authBoot.Enabled=$true
$authAction=$authDefinition.Actions.Create(0)
$authAction.Path=Join-Path $authRoot 'venv\Scripts\python.exe'
$authAction.WorkingDirectory=$authRoot
$authAction.Arguments='"'+(Join-Path $authRoot 'scripts\watch_schwab_authorization.py')+'"'
$authPassword=$null
$authPointer=[IntPtr]::Zero
try{
 if($PromptCredential){
  Write-Host 'JJTrade: supervisión de Schwab sin sesión RDP. No habilita órdenes.'
  Write-Host 'Introduce la contraseña de Windows de Administrator de esta VPS (NO la de Schwab).'
  $authSecure=Read-Host 'Contraseña de Administrator (entrada oculta)' -AsSecureString
  $authPointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($authSecure)
  $authPassword=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($authPointer)
 }
 # Reuse a stored credential if permitted, otherwise only accept hidden input.
 $authRegistered=$authFolder.RegisterTaskDefinition($authName,$authDefinition,2,$authIdentity.User.Value,$authPassword,1,$null)
}catch{
 [pscustomobject]@{State='REGISTRATION_REQUIRES_HIDDEN_CREDENTIAL';ErrorCode=$_.Exception.HResult;TaskEnabled=$false;OtherServicesChanged=$false}|ConvertTo-Json
 exit 2
}finally{
 $authPassword=$null
 if($authPointer -ne [IntPtr]::Zero){[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($authPointer)}
 if($authSecure){$authSecure.Dispose()}
}
$authRegistered.Enabled=$true
$authRegistered.Run($null)|Out-Null
[pscustomobject]@{State='REGISTERED_AND_STARTED';Task=$authName;LogonType=$authRegistered.Definition.Principal.LogonType;Enabled=$authRegistered.Enabled;OtherServicesChanged=$false}|ConvertTo-Json
