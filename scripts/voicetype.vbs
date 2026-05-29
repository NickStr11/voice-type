' VoiceType watchdog: keeps pythonw -m voice_type.main alive.
' Auto-started by Startup\VoiceType.lnk. Runs hidden in wscript.exe.
' Checks every 30s, restarts worker if missing. Initial 15s delay
' lets the USB microphone and audio stack come up after logon.

Option Explicit

Dim fso, shell, wmi, repoRoot, pythonw, cmdLine, checkIntervalMs, startupDelayMs
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
Set wmi = GetObject("winmgmts:\\.\root\cimv2")

repoRoot = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
pythonw = fso.BuildPath(repoRoot, ".venv\Scripts\pythonw.exe")
cmdLine = """" & pythonw & """ -m voice_type.main"
checkIntervalMs = 30000
startupDelayMs = 15000

If Not fso.FileExists(pythonw) Then
    ' Silent fail — no MsgBox, watchdog should never pop dialogs on startup
    WScript.Quit 1
End If

' Give the system time to finish logon and initialise USB audio
WScript.Sleep startupDelayMs

shell.CurrentDirectory = repoRoot

Do
    If Not IsWorkerAlive() Then
        shell.Run cmdLine, 0, False
    End If
    WScript.Sleep checkIntervalMs
Loop

Function IsWorkerAlive()
    Dim procs, proc
    Set procs = wmi.ExecQuery( _
        "SELECT ProcessId FROM Win32_Process " & _
        "WHERE (Name = 'pythonw.exe' OR Name = 'python.exe') " & _
        "AND CommandLine LIKE '%voice_type.main%'")
    IsWorkerAlive = False
    For Each proc In procs
        IsWorkerAlive = True
        Exit For
    Next
End Function
