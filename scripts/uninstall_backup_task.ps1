$ErrorActionPreference = "Stop"
$taskName = "KkobungBotDailyBackup"
$task = Get-ScheduledTask `
    -TaskName $taskName `
    -ErrorAction SilentlyContinue

if ($null -eq $task) {
    Write-Output "등록된 작업이 없습니다: $taskName"
    exit 0
}

Unregister-ScheduledTask `
    -TaskName $taskName `
    -Confirm:$false

Write-Output "일일 외부 백업 작업 제거 완료: $taskName"
