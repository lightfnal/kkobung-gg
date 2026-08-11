$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = (
    "C:\Users\게무\AppData\Local\Programs\Python\Python313\python.exe"
)
$botEntryPoint = Join-Path $projectRoot "bot.py"

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "Python 실행 파일을 찾을 수 없습니다: $pythonExecutable"
}

if (-not (Test-Path -LiteralPath $botEntryPoint)) {
    throw "봇 실행 파일을 찾을 수 없습니다: $botEntryPoint"
}

Set-Location -LiteralPath $projectRoot

& $pythonExecutable $botEntryPoint
exit $LASTEXITCODE
