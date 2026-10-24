$ErrorActionPreference = 'Stop'
try {
    $directory = Join-Path (Split-Path -Parent $PSScriptRoot) 'exports\private_runtime'
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    if (-not $sid.Value.EndsWith('-500')) { throw 'Administrator required' }
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($sid)
    $inherit = [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
    foreach ($principal in @($sid, (New-Object Security.Principal.SecurityIdentifier 'S-1-5-18'))) {
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($principal, 'FullControl', $inherit, 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $directory -AclObject $acl
    exit 0
} catch { exit 1 }
