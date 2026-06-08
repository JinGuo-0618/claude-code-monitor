CreateObject("WScript.Shell").Run "pythonw """ & CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\status_monitor.py""", 0, False
