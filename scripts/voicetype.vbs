Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d D:\code\2026\3\voice-type && uv run python -m voice_type.main", 0, False
