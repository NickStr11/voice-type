$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$ensureScript = Join-Path $PSScriptRoot "ensure-running.ps1"
$powershellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$taskPrefix = "VoiceType"

if (-not (Test-Path -LiteralPath $ensureScript)) {
    throw "ensure-running.ps1 not found: $ensureScript"
}

$taskCommand = "`"$powershellExe`" -NoProfile -ExecutionPolicy Bypass -File `"$ensureScript`""
$resumeQuery = "*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1]]"

function Register-VoiceTypeTask {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & schtasks.exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to register scheduled task: $Name"
    }
}

Register-VoiceTypeTask -Name "$taskPrefix Ensure Running Logon" -Arguments @(
    "/Create",
    "/TN", "$taskPrefix Ensure Running Logon",
    "/SC", "ONLOGON",
    "/TR", $taskCommand,
    "/RL", "LIMITED",
    "/F"
)

Register-VoiceTypeTask -Name "$taskPrefix Ensure Running Resume" -Arguments @(
    "/Create",
    "/TN", "$taskPrefix Ensure Running Resume",
    "/SC", "ONEVENT",
    "/EC", "System",
    "/MO", $resumeQuery,
    "/TR", $taskCommand,
    "/RL", "LIMITED",
    "/F"
)

Write-Output "Installed VoiceType resilience tasks:"
Write-Output "  VoiceType Ensure Running Logon"
Write-Output "  VoiceType Ensure Running Resume"
Write-Output ""
Write-Output "Run this to verify:"
Write-Output "  powershell -ExecutionPolicy Bypass -File scripts\audit-autostart.ps1"
