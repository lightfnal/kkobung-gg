param(
    [switch]$StopRunningTask
)

$ErrorActionPreference = "Stop"
$taskName = "KkobungBot"
$task = Get-ScheduledTask `
    -TaskName $taskName `
    -ErrorAction SilentlyContinue

if ($null -eq $task) {
    Write-Output "등록된 작업이 없습니다: $taskName"
    exit 0
}

if ($StopRunningTask) {
    Stop-ScheduledTask `
        -TaskName $taskName `
        -ErrorAction SilentlyContinue
}

Unregister-ScheduledTask `
    -TaskName $taskName `
    -Confirm:$false

Write-Output "작업 스케줄러 제거 완료: $taskName"
