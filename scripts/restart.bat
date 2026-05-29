@echo off
REM Kill any running VoiceType worker, then relaunch from the repo root.
REM Lives in scripts/ — "%~dp0.." resolves to the project root regardless
REM of where the repo is checked out.
taskkill /f /fi "WINDOWTITLE eq VoiceType*" >nul 2>&1
taskkill /f /fi "IMAGENAME eq python.exe" /fi "MEMUSAGE gt 50000" >nul 2>&1
timeout /t 1 /nobreak >nul
cd /d "%~dp0.."
start "" /min cmd /c "title VoiceType && uv run python -m voice_type.main"
echo VoiceType restarted.
timeout /t 2 /nobreak >nul
