param(
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"

$taskName = "KkobungBot"
$launcherPath = Join-Path $PSScriptRoot "start_bot.ps1"
$powerShellPath = (
    "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
)
$userId = "$env:USERDOMAIN\$env:USERNAME"

if (-not (Test-Path -LiteralPath $launcherPath)) {
    throw "봇 실행 스크립트를 찾을 수 없습니다: $launcherPath"
}

$action = New-ScheduledTaskAction `
    -Execute $powerShellPath `
    -Argument (
        '-NoProfile -NonInteractive -WindowStyle Hidden ' +
        '-ExecutionPolicy Bypass -File "' + $launcherPath + '"'
    ) `
    -WorkingDirectory (Split-Path -Parent $PSScriptRoot)

$trigger = New-ScheduledTaskTrigger `
    -AtLogOn `
    -User $userId

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 10 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
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
    -Description "꼬붕봇 v0.3.0 자동 시작 및 장애 재가동" `
    -Force | Out-Null

if ($StartNow) {
    Start-ScheduledTask -TaskName $taskName
}

Write-Output "작업 스케줄러 등록 완료: $taskName"
Write-Output "로그인 시 자동 시작: 사용"
Write-Output "비정상 종료 재시작: 1분 간격, 최대 10회"
Write-Output "즉시 시작: $($StartNow.IsPresent)"
