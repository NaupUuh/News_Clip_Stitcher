' ====================================================================
'  News Clip Stitcher - MO AN HOAN TOAN (khong nhap nhay cua so cmd)
'  Double-click file nay de chay. Cua so cmd khong bao gio hien ra.
'  Muon xem loi: chay run.bat debug
' ====================================================================
Option Explicit
Dim sh, fso, here, bat
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

here = fso.GetParentFolderName(WScript.ScriptFullName)
bat  = here & "\run.bat"

If Not fso.FileExists(bat) Then
    MsgBox "Khong tim thay run.bat cung thu muc.", 16, "News Clip Stitcher"
    WScript.Quit 1
End If

' 0 = cua so an, False = khong cho doi -> tools tat la cmd tat theo
sh.Run """" & bat & """ hidden", 0, False
