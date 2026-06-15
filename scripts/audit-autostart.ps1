param(
    [switch]$RemoveStartupLinkIfRunKeyExists
)

$ErrorActionPreference = "Stop"

$runPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$startupDir = [Environment]::GetFolderPath("Startup")
$startupLink = Join-Path $startupDir "VoiceType.lnk"

function Get-RunValue {
    if (-not (Test-Path -LiteralPath $runPath)) {
        return $null
    }
    $item = Get-ItemProperty -LiteralPath $runPath
    return $item.VoiceType
}

$runValue = Get-RunValue
$startupLinkExists = Test-Path -LiteralPath $startupLink

Write-Output "VoiceType autostart audit"
Write-Output ""
Write-Output "HKCU Run key:"
if ([string]::IsNullOrWhiteSpace($runValue)) {
    Write-Output "  VoiceType: <missing>"
} else {
    Write-Output "  VoiceType: $runValue"
}

Write-Output ""
Write-Output "Startup link:"
if ($startupLinkExists) {
    Write-Output "  present: $startupLink"
} else {
    Write-Output "  missing: $startupLink"
}

Write-Output ""
Write-Output "WMI startup commands:"
$startupCommands = Get-CimInstance Win32_StartupCommand |
    Where-Object { $_.Name -match "VoiceType|voice" -or $_.Command -match "voice_type|voicetype" }
if ($startupCommands) {
    $startupCommands | ForEach-Object {
        Write-Output ("  {0} | {1} | {2} | {3}" -f $_.Name, $_.Command, $_.Location, $_.User)
    }
} else {
    Write-Output "  <none>"
}

Write-Output ""
Write-Output "Running VoiceType workers:"
$workers = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match "voice_type\.main" }
if ($workers) {
    $workers | ForEach-Object {
        Write-Output ("  PID {0} | {1} | {2}" -f $_.ProcessId, $_.Name, $_.CommandLine)
    }
} else {
    Write-Output "  <none>"
}

Write-Output ""
Write-Output "Running watchdogs:"
$watchdogs = Get-CimInstance Win32_Process -Filter "Name = 'wscript.exe' OR Name = 'cscript.exe'" |
    Where-Object { $_.CommandLine -match "voicetype\.vbs|VoiceType\.lnk" }
if ($watchdogs) {
    $watchdogs | ForEach-Object {
        Write-Output ("  PID {0} | {1} | {2}" -f $_.ProcessId, $_.Name, $_.CommandLine)
    }
} else {
    Write-Output "  <none>"
}

Write-Output ""
if (-not [string]::IsNullOrWhiteSpace($runValue) -and $startupLinkExists) {
    Write-Output "Status: duplicate login triggers detected (HKCU Run + Startup link)."
    if ($RemoveStartupLinkIfRunKeyExists) {
        Remove-Item -LiteralPath $startupLink -Force
        Write-Output "Removed duplicate Startup link: $startupLink"
    } else {
        Write-Output "Run again with -RemoveStartupLinkIfRunKeyExists to remove the Startup link."
    }
} elseif (-not [string]::IsNullOrWhiteSpace($runValue)) {
    Write-Output "Status: HKCU Run key is the only login trigger."
} elseif ($startupLinkExists) {
    Write-Output "Status: Startup link is the only login trigger."
} else {
    Write-Output "Status: no VoiceType login trigger found."
}
