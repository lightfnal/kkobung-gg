$ErrorActionPreference = "Stop"

$taskName = "KkobungBotDailyBackup"
$launcherPath = Join-Path $PSScriptRoot "run_external_backup.ps1"
$powerShellPath = (
    "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
)
$userId = "$env:USERDOMAIN\$env:USERNAME"

$action = New-ScheduledTaskAction `
    -Execute $powerShellPath `
    -Argument (
        '-NoProfile -NonInteractive -WindowStyle Hidden ' +
        '-ExecutionPolicy Bypass -File "' + $launcherPath + '"'
    ) `
    -WorkingDirectory (Split-Path -Parent $PSScriptRoot)

$trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At "03:00"

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal `
    -UserId $userId `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "꼬붕봇 SQLite 일일 외부 백업 및 무결성 검사" `
    -Force | Out-Null

Write-Output "일일 외부 백업 작업 등록 완료: $taskName"
Write-Output "실행 시각: 매일 03:00"
