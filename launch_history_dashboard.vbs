Option Explicit

Dim fso, shell, projectDir, pythonwPath, mainPath
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonwPath = fso.BuildPath(projectDir, ".venv\Scripts\pythonw.exe")
mainPath = fso.BuildPath(projectDir, "main.py")

If Not fso.FileExists(pythonwPath) Then
    MsgBox "History Dashboard setup is incomplete." & vbCrLf & vbCrLf & _
           "Run install_dependencies.bat once, then try again.", _
           vbExclamation, "History Dashboard"
    WScript.Quit 1
End If

shell.CurrentDirectory = projectDir
shell.Run Chr(34) & pythonwPath & Chr(34) & " " & Chr(34) & mainPath & Chr(34), 0, False
