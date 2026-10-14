param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$Config,
    [switch]$Enable
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$configPath = (Resolve-Path -LiteralPath $Config).Path
if ($configPath.Contains('"') -or $configPath.Contains("`n")) { throw 'Invalid configuration path' }
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath -m ops.setup_check --config $configPath
    if ($LASTEXITCODE -ne 0) { throw 'CLI/auth/sandbox enrollment is BLOCKED; no task registered' }
    if (-not $Enable) {
        Write-Output 'CHECK ONLY. No trigger enabled. Rerun with -Enable only after reviewing enrollment.'
        return
    }
    $taskName = 'STARK-T2SQL-Supervised-Coordinator'
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'Task exists; inspect rather than overwrite it' }
    $arguments = '-m ops.coordinator poll --config "' + $configPath + '"'
    $action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $projectRoot
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    $principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State
} finally { Pop-Location }
