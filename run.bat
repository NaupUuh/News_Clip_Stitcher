@echo off
rem ===================================================================
rem  News Clip Stitcher - chay AN, KHONG hien cua so cmd.
rem  Muon xem cua so cmd de doc loi:  go  run.bat debug
rem ===================================================================
chcp 65001 >nul
cd /d "%~dp0"

if /i "%~1"=="debug" goto :run
if /i "%~1"=="hidden" goto :run

rem --- Chua an: tu goi lai chinh no qua 1 VBS tam de chay an ---
set "VBS=%TEMP%\ncs_hide_%RANDOM%%RANDOM%.vbs"
> "%VBS%" echo CreateObject("WScript.Shell").Run """%~f0"" hidden", 0, False
cscript //nologo "%VBS%" >nul 2>&1
del "%VBS%" >nul 2>&1
exit /b


:run
title News Clip Stitcher v1.14.0

set "PY="
for %%P in (
  "C:\ReverseEngineering\Scripts\venv\Scripts\python.exe"
  "C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe"
) do (
  if not defined PY if exist %%P set "PY=%%~P"
)
if not defined PY set "PY=python"

rem --- ffmpeg: dua thu muc chua ffmpeg.exe vao PATH cho ca phien ---
set "FFDIR="
for %%D in (
  "%~dp0ffmpeg\bin"
  "C:\ReverseEngineering\thirdparty\ffmpeg-9.0.2-essentials_build\bin"
  "C:\ffmpeg-9.0.2-essentials_build\bin"
  "C:\ffmpeg-9.0.1-essentials_build\bin"
  "C:\ffmpeg\bin"
) do (
  if not defined FFDIR if exist "%%~D\ffmpeg.exe" set "FFDIR=%%~D"
)
if defined FFDIR set "PATH=%FFDIR%;%PATH%"

rem --- che do AN: moi thu ghi ra log, khong hien ra man hinh ---
set "HIDDEN=1"
if /i "%~1"=="debug" set "HIDDEN="
if defined HIDDEN (
  set "LOG=%TEMP%\News_Clip_Stitcher_run.log"
) else (
  set "LOG=con"
)

if defined HIDDEN (
  "%PY%" -c "import PIL" >nul 2>&1
) else (
  "%PY%" -c "import PIL" >nul 2>&1
)
if errorlevel 1 (
    if defined HIDDEN (
        echo [%DATE% %TIME%] Dang cai Pillow... >> "%LOG%"
        "%PY%" -m pip install pillow --quiet >> "%LOG%" 2>&1
    ) else (
        echo Dang cai Pillow...
        "%PY%" -m pip install pillow --quiet
    )
)

if defined HIDDEN (
    echo [%DATE% %TIME%] Khoi dong News Clip Stitcher... >> "%LOG%"
    "%PY%" main.py >> "%LOG%" 2>&1
) else (
    echo Khoi dong News Clip Stitcher...
    "%PY%" main.py
)

rem --- Chi giu cua so lai khi chay che do debug (co nguoi doc loi) ---
if not defined HIDDEN (
    if errorlevel 1 (
        echo.
        echo === LOI - xem chi tiet o tren ===
        pause
    )
)
exit /b
