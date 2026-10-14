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
title News Clip Stitcher v1.27.1

rem ===================================================================
rem  CHON PYTHON (>= 3.10)
rem  Truoc day file nay chi do 2 duong dan CO DINH cua may build. May khac
rem  khong co 2 duong dan do -> roi xuong "python" trong PATH, ma may do
rem  cai Python 3.9 -> tool chet voi loi:
rem      AttributeError: 'int' object has no attribute 'bit_count'
rem  (bit_count() chi co tu Python 3.10).
rem  Gio thu theo thu tu: py launcher -> duong dan co dinh -> PATH.
rem ===================================================================
set "PY="

rem --- 1) py launcher (ban moi nhat truoc) ---
call :try_py -3.14
call :try_py -3.13
call :try_py -3.12
call :try_py -3.11
call :try_py -3.10

rem --- 2) cac duong dan hay gap ---
for %%P in (
  "C:\ReverseEngineering\Scripts\venv\Scripts\python.exe"
  "C:\Users\Admin\AppData\Local\Programs\Python\Python314\python.exe"
  "C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe"
  "C:\Users\Admin\AppData\Local\Programs\Python\Python312\python.exe"
  "C:\Users\Admin\AppData\Local\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "C:\Python313\python.exe"
  "C:\Python312\python.exe"
) do (
  if not defined PY if exist %%P set "PY=%%~P"
)

rem --- 3) python trong PATH ---
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

rem --- Canh bao neu Python qua cu (< 3.10) ---
%PY% -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 (
  echo [%DATE% %TIME%] CANH BAO: Python qua cu, nen cai Python 3.11 tro len. >> "%LOG%"
  echo [%DATE% %TIME%]   Python dang dung: %PY% >> "%LOG%"
)

%PY% -c "import PIL" >nul 2>&1
if errorlevel 1 (
    if defined HIDDEN (
        echo [%DATE% %TIME%] Dang cai Pillow... >> "%LOG%"
        %PY% -m pip install pillow --quiet >> "%LOG%" 2>&1
    ) else (
        echo Dang cai Pillow...
        %PY% -m pip install pillow --quiet
    )
)

if defined HIDDEN (
    echo [%DATE% %TIME%] Khoi dong News Clip Stitcher... (Python: %PY%) >> "%LOG%"
    %PY% main.py >> "%LOG%" 2>&1
) else (
    echo Khoi dong News Clip Stitcher... (Python: %PY%)
    %PY% main.py
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


rem ===================================================================
rem  Thu 1 ban Python qua py launcher. Chay duoc thi ghim vao %PY%.
rem ===================================================================
:try_py
if defined PY exit /b
py %1 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py %1"
exit /b
