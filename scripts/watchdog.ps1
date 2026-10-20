param(
    [int]$StartupDelaySeconds = 15,
    [int]$CheckIntervalSeconds = 30,
    # Whisper health: a live worker whose whisper-server never answers is the
    # failure from 2026-10-12..20 (logon-started worker could not see the model
    # and every dictation silently went to the cloud). Restart it, at most once
    # per $WhisperRestartCooldownSeconds so a truly missing model cannot loop.
    [int]$WhisperGraceSeconds = 120,
    [int]$WhisperFailedChecks = 4,
    [int]$WhisperRestartCooldownSeconds = 1800
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

function Test-WhisperServer {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8178/health" -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Restart-VoiceTypeWorker {
    param([object[]]$Workers)
    foreach ($worker in $Workers) {
        try { Stop-Process -Id $worker.ProcessId -Force -ErrorAction Stop } catch {}
    }
    Start-Sleep -Seconds 2
    Start-VoiceTypeWorker
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
    $whisperFails = 0
    $lastWhisperRestart = [datetime]::MinValue
    $lastTick = Get-Date
    while ($true) {
        try {
            # A long gap means the machine slept: the worker rebuilds whisper-server
            # itself after resume, so start counting failures from scratch.
            $now = Get-Date
            if (($now - $lastTick).TotalSeconds -gt ($CheckIntervalSeconds * 3)) {
                $whisperFails = 0
            }
            $lastTick = $now

            $workers = @(Get-VoiceTypeWorkers)
            if ($workers.Count -eq 0) {
                Write-WatchdogLog "worker missing"
                $whisperFails = 0
                Start-VoiceTypeWorker
            } else {
                if (($ticks % 20) -eq 0) {
                    $workerIds = ($workers | ForEach-Object { $_.ProcessId }) -join ","
                    Write-WatchdogLog "worker alive: $workerIds"
                }

                $oldest = ($workers | Sort-Object CreationDate | Select-Object -First 1).CreationDate
                $workerAge = ($now - $oldest).TotalSeconds
                if ($workerAge -lt $WhisperGraceSeconds -or (Test-WhisperServer)) {
                    $whisperFails = 0
                } else {
                    $whisperFails += 1
                    if ($whisperFails -ge $WhisperFailedChecks) {
                        $sinceRestart = ($now - $lastWhisperRestart).TotalSeconds
                        if ($sinceRestart -ge $WhisperRestartCooldownSeconds) {
                            Write-WatchdogLog "whisper-server down for $whisperFails checks; restarting worker"
                            $lastWhisperRestart = $now
                            $whisperFails = 0
                            Restart-VoiceTypeWorker -Workers $workers
                        } elseif ($whisperFails -eq $WhisperFailedChecks) {
                            Write-WatchdogLog "whisper-server still down; restart cooldown active"
                        }
                    }
                }
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
