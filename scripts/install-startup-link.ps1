$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$watchdogScript = Join-Path $PSScriptRoot "watchdog.ps1"
$powershellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$startupDir = [Environment]::GetFolderPath("Startup")
$startupLink = Join-Path $startupDir "VoiceType.lnk"
$runPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$runValueName = "VoiceType"
$watchdogCommand = "`"$powershellExe`" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchdogScript`""
$startupApprovedEnabled = [byte[]](2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

if (-not (Test-Path -LiteralPath $watchdogScript)) {
    throw "watchdog.ps1 not found: $watchdogScript"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($startupLink)
$shortcut.TargetPath = $powershellExe
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchdogScript`""
$shortcut.WorkingDirectory = $repoRoot
$shortcut.WindowStyle = 7
$shortcut.Description = "VoiceType watchdog - keeps dictation running after sleep"
$shortcut.Save()

if (-not (Test-Path -LiteralPath $runPath)) {
    New-Item -Path $runPath -Force | Out-Null
}
Set-ItemProperty -LiteralPath $runPath -Name $runValueName -Value $watchdogCommand

if (-not (Test-Path -LiteralPath $runApprovedPath)) {
    New-Item -Path $runApprovedPath -Force | Out-Null
}
if (-not (Test-Path -LiteralPath $startupApprovedPath)) {
    New-Item -Path $startupApprovedPath -Force | Out-Null
}
Set-ItemProperty -LiteralPath $runApprovedPath -Name $runValueName -Type Binary -Value $startupApprovedEnabled
Set-ItemProperty -LiteralPath $startupApprovedPath -Name "VoiceType.lnk" -Type Binary -Value $startupApprovedEnabled

Write-Output "Installed Startup link:"
Write-Output "  $startupLink"
Write-Output "  $powershellExe $($shortcut.Arguments)"
Write-Output "Installed HKCU Run fallback:"
Write-Output "  $runValueName = $watchdogCommand"

