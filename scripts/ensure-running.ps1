param(
    [switch]$RestartWorker
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $repoRoot ".venv\Scripts\pythonw.exe"
$watchdogScript = Join-Path $PSScriptRoot "watchdog.ps1"
$powershellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$workerPattern = "voice_type\.main"
$watchdogPattern = [regex]::Escape($watchdogScript)

function Get-VoiceTypeWorkers {
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
        Where-Object { $_.CommandLine -match $workerPattern }
}

function Get-VoiceTypeWatchdogs {
    Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe' OR Name = 'wscript.exe' OR Name = 'cscript.exe'" |
        Where-Object { $_.CommandLine -match $watchdogPattern }
}

function Start-VoiceTypeWorker {
    if (-not (Test-Path -LiteralPath $pythonw)) {
        throw "pythonw.exe not found: $pythonw"
    }
    Start-Process -FilePath $pythonw -ArgumentList "-m", "voice_type.main" -WorkingDirectory $repoRoot -WindowStyle Hidden
}

function Start-VoiceTypeWatchdog {
    if (-not (Test-Path -LiteralPath $watchdogScript)) {
        throw "Watchdog script not found: $watchdogScript"
    }
    Start-Process -FilePath $powershellExe -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", "`"$watchdogScript`"" -WorkingDirectory $repoRoot -WindowStyle Hidden
}

$watchdogs = @(Get-VoiceTypeWatchdogs)
if ($watchdogs.Count -eq 0) {
    Start-VoiceTypeWatchdog
    Write-Output "VoiceType ensure-running complete"
    Write-Output "  started watchdog; worker will be launched by watchdog"
    exit 0
}

if ($RestartWorker) {
    Get-VoiceTypeWorkers | ForEach-Object {
        try {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
        } catch {}
    }
    Start-Sleep -Seconds 1
}

$workers = @(Get-VoiceTypeWorkers)
if ($workers.Count -eq 0) {
    Start-VoiceTypeWorker
}

Write-Output "VoiceType ensure-running complete"
Write-Output ("  workers before/after check: {0}" -f $workers.Count)
Write-Output ("  watchdogs before/after check: {0}" -f $watchdogs.Count)
