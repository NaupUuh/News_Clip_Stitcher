@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Sua loi Cap nhat (SSL certificate) - News Clip Stitcher

echo ============================================================
echo   SUA LOI "Khong cap nhat duoc"
echo   (CERTIFICATE_VERIFY_FAILED: unable to get local issuer...)
echo ------------------------------------------------------------
echo   May nay thieu kho chung chi CA nen Python khong tai duoc
echo   ban moi tu GitHub. File nay tu sua, khong can cai them gi.
echo   Config + video cu duoc giu nguyen.
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Sua_loi_cap_nhat.ps1"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo ============================================================
  echo   Neu van khong duoc, lam theo huong dan o tren ^(copy tu o Z^).
  echo ============================================================
)
echo.
pause
exit /b %RC%
