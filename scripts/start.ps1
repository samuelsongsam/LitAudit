param(
    [switch]$Demo,
    [switch]$Lite,
    [string]$RunId = "",
    [string]$Workspace = "",
    [switch]$NoBrowser,
    [int]$Port = 8787
)
$ErrorActionPreference = "Stop"
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = Join-Path $taskRoot ".venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskPython = (Get-Command python -ErrorAction Stop).Source
}
if ($Workspace) {
    New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
    $env:LITAUDIT_HOME = (Resolve-Path -LiteralPath $Workspace).Path
}
$taskDataRoot = if ($env:LITAUDIT_HOME) { $env:LITAUDIT_HOME } else { $taskRoot }
$taskRun = $RunId
if ($Demo -or $Lite) {
    $env:LITAUDIT_MAP_EMBEDDER = "hash"
    $env:LITAUDIT_RERANK_EMBEDDER = "hash"
}
if ($Demo -and -not $taskRun) {
    if (Test-Path -LiteralPath (Join-Path $taskDataRoot "runs/audit_20260915T131753Z_a42e86/run_manifest.json")) {
        $taskRun = "audit_20260915T131753Z_a42e86"
    } elseif (Test-Path -LiteralPath (Join-Path $taskDataRoot "runs/phase2-real/run_manifest.json")) {
        $taskRun = "phase2-real"
    }
}
& $taskPython -m src.cli doctor
if ($LASTEXITCODE -ne 0) {
    Write-Warning "随包基准数据未就绪，可在空工作区导入PDF；回放案例时请确认data和runs目录完整。"
}
$taskArguments = @("-m", "src.cli", "ui", "--port", [string]$Port)
if ($taskRun) { $taskArguments += @("--run-id", $taskRun) }
if ($NoBrowser) { $taskArguments += "--no-browser" }
& $taskPython @taskArguments
