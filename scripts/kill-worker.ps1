# Kill any running VoiceType worker(s).
# The worker runs as pythonw.exe (or python.exe) -m voice_type.main, started
# by the voicetype.vbs watchdog. taskkill can't filter by command line, so we
# match Win32_Process.CommandLine here.
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match 'voice_type\.main' } |
    ForEach-Object {
        try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
    }
