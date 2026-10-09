param(
    [int]$StartupDelaySeconds = 15,
    [int]$CheckIntervalSeconds = 30
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $repoRoot ".venv\Scripts\pythonw.exe"
$runtimeDir = Join-Path $repoRoot "runtime"
$logPath = Join-Path $runtimeDir "voicetype-watchdog.log"
$workerPattern = "voice_type\.main"
$mutexName = "Local\VoiceTypeWatchdog"

function Write-WatchdogLog {
    param([string]$Message)
    if (-not (Test-Path -LiteralPath $runtimeDir)) {
        New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    }
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "$stamp | $Message"
}

function Get-VoiceTypeWorkers {
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
        Where-Object { $_.CommandLine -match $workerPattern }
}

function Start-VoiceTypeWorker {
    if (-not (Test-Path -LiteralPath $pythonw)) {
        throw "pythonw.exe not found: $pythonw"
    }
    Start-Process -FilePath $pythonw -ArgumentList "-m", "voice_type.main" -WorkingDirectory $repoRoot -WindowStyle Hidden
    Write-WatchdogLog "started worker"
}

$createdNew = $false
$mutex = [System.Threading.Mutex]::new($false, $mutexName, [ref]$createdNew)
$hasMutex = $mutex.WaitOne(0)

if (-not $hasMutex) {
    Write-WatchdogLog "watchdog already running; exiting"
    exit 0
}

try {
    Write-WatchdogLog "watchdog started; startup delay ${StartupDelaySeconds}s"
    Start-Sleep -Seconds $StartupDelaySeconds

    $ticks = 0
    while ($true) {
        try {
            $workers = @(Get-VoiceTypeWorkers)
            if ($workers.Count -eq 0) {
                Write-WatchdogLog "worker missing"
                Start-VoiceTypeWorker
            } elseif (($ticks % 20) -eq 0) {
                $workerIds = ($workers | ForEach-Object { $_.ProcessId }) -join ","
                Write-WatchdogLog "worker alive: $workerIds"
            }
        } catch {
            Write-WatchdogLog "watchdog error: $($_.Exception.Message)"
        }

        $ticks += 1
        Start-Sleep -Seconds $CheckIntervalSeconds
    }
} finally {
    if ($hasMutex) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
