@echo off
REM Kill any running VoiceType worker, then relaunch from the repo root.
REM Lives in scripts/ — "%~dp0.." resolves to the project root regardless
REM of where the repo is checked out.
REM
REM The worker runs as pythonw.exe -m voice_type.main (see voicetype.vbs).
REM taskkill can't match on command line, so killing goes through
REM kill-worker.ps1 which filters Win32_Process by CommandLine. We relaunch
REM via the same pythonw path the watchdog uses, so the 30s watchdog check
REM sees the worker alive and never double-spawns — exactly one ends up running.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill-worker.ps1"
timeout /t 1 /nobreak >nul
cd /d "%~dp0.."
start "" /b ".venv\Scripts\pythonw.exe" -m voice_type.main
echo VoiceType restarted.
timeout /t 2 /nobreak >nul
