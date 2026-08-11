$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = (
    "C:\Users\게무\AppData\Local\Programs\Python\Python313\python.exe"
)
$backupEntryPoint = Join-Path $projectRoot "external_backup.py"

Set-Location -LiteralPath $projectRoot
& $pythonExecutable $backupEntryPoint
exit $LASTEXITCODE
