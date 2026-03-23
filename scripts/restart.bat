@echo off
taskkill /f /fi "WINDOWTITLE eq VoiceType*" >nul 2>&1
taskkill /f /fi "IMAGENAME eq python.exe" /fi "MEMUSAGE gt 50000" >nul 2>&1
timeout /t 1 /nobreak >nul
start "" /min cmd /c "cd /d D:\code\2026\3\voice-type && title VoiceType && uv run python -m voice_type.main"
echo VoiceType restarted.
timeout /t 2 /nobreak >nul
