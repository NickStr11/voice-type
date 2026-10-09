Option Explicit

Dim shell, command
Set shell = CreateObject("WScript.Shell")

command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""D:\code\2026\3\voice-type\scripts\watchdog.ps1"""
shell.Run command, 0, False
