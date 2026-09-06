' Typist Translator - start with no console window
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = CreateObject("Scripting.FileSystemObject") _
    .GetParentFolderName(WScript.ScriptFullName)
shell.Run "pythonw main.py", 0, False
