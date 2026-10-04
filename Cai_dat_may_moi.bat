@echo off
chcp 65001 >nul
title Cai dat News Clip Stitcher
setlocal

echo ============================================================
echo   CAI DAT NEWS CLIP STITCHER (may moi)
echo ------------------------------------------------------------
echo   Chi chay file nay MOT LAN. Sau do moi lan cap nhat
echo   chi can bam nut "Cap nhat" trong tool.
echo ============================================================
echo.

set "DEST=%~dp0News_Clip_Stitcher"
set "ZIP=%TEMP%\ncs_install.zip"
set "URL=https://api.github.com/repos/NaupUuh/News_Clip_Stitcher/zipball/main"

echo [1/4] Dang tai tool tu GitHub...
powershell -NoProfile -Command ^
  "$ProgressPreference='SilentlyContinue';" ^
  "Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%' -Headers @{ 'Accept'='application/vnd.github+json' } -UseBasicParsing"
if not exist "%ZIP%" (
  echo   LOI: khong tai duoc. Kiem tra mang roi chay lai.
  pause & exit /b 1
)
for %%A in ("%ZIP%") do echo   Da tai: %%~zA bytes

echo [2/4] Dang giai nen...
if exist "%TEMP%\ncs_x" rmdir /s /q "%TEMP%\ncs_x"
powershell -NoProfile -Command ^
  "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%TEMP%\ncs_x' -Force"
if not exist "%TEMP%\ncs_x" (
  echo   LOI: giai nen that bai.
  pause & exit /b 1
)

echo [3/4] Dang chep vao: %DEST%
if not exist "%DEST%" mkdir "%DEST%"
for /d %%D in ("%TEMP%\ncs_x\*") do (
  xcopy "%%D\*" "%DEST%\" /E /I /Y /Q >nul
)
del "%ZIP%" >nul 2>&1
rmdir /s /q "%TEMP%\ncs_x" >nul 2>&1

if not exist "%DEST%\main.py" (
  echo   LOI: thieu main.py - cai dat that bai.
  pause & exit /b 1
)

echo [4/4] Xong.
echo.
echo ============================================================
echo   DA CAI DAT vao:  %DEST%
echo.
echo   Mo tool bang: Mo_An.vbs   (chay an, khong hien cmd)
echo   Lan sau co ban moi: mo tool roi bam nut "Cap nhat"
echo ============================================================
echo.
choice /C YN /N /M "Mo tool ngay bay gio? [Y/N] "
if errorlevel 2 goto :end
start "" "%DEST%\Mo_An.vbs"

:end
endlocal
