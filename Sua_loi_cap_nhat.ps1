# -*- coding: utf-8 -*-
<#
    Sua loi "Khong cap nhat duoc" (CERTIFICATE_VERIFY_FAILED) cho News Clip Stitcher.

    Chay:  powershell -NoProfile -ExecutionPolicy Bypass -File Sua_loi_cap_nhat.ps1

    Cach lam (2 duong doc lap):
      A) Tai chung chi CA (cacert.pem) bang PowerShell -> chay updater.py --apply
      B) Neu A hong: PowerShell tai ca goi tool roi chep de (giu config.json)
#>
$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$Base    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Pem     = Join-Path $Base 'cacert.pem'
$Zip     = Join-Path $env:TEMP 'ncs_fix.zip'
$Dir     = Join-Path $env:TEMP 'ncs_fix_x'
$Keep    = Join-Path $env:TEMP 'ncs_config_keep.json'
$RawPem  = 'https://raw.githubusercontent.com/NaupUuh/News_Clip_Stitcher/main/cacert.pem'
$ApiPem  = 'https://api.github.com/repos/NaupUuh/News_Clip_Stitcher/contents/cacert.pem?ref=main'
$ZipUrl  = 'https://api.github.com/repos/NaupUuh/News_Clip_Stitcher/zipball/main'
$GhZip   = 'https://github.com/NaupUuh/News_Clip_Stitcher/archive/refs/heads/main.zip'

function Say($m) { Write-Host $m }

function Find-Python {
    $cands = @(
        (Join-Path $Base 'venv\Scripts\python.exe'),
        'C:\ReverseEngineering\Scripts\venv\Scripts\python.exe',
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
    )
    foreach ($c in $cands) { if (Test-Path $c) { return $c } }
    $w = Get-Command python -ErrorAction SilentlyContinue
    if ($w) { return $w.Source }
    $w = Get-Command py -ErrorAction SilentlyContinue
    if ($w) { return $w.Source }
    return $null
}

# ---------------------------------------------------------------- cach B
function Get-WholeTool {
    Say ''
    Say '[Cach 2/2] Tai ca goi tool bang PowerShell...'
    $ok = $false
    foreach ($u in @($ZipUrl, $GhZip)) {
        try {
            if (Test-Path $Zip) { Remove-Item $Zip -Force }
            if (Test-Path $Dir) { Remove-Item $Dir -Recurse -Force }
            $headers = @{}
            if ($u -like '*api.github.com*') { $headers['Accept'] = 'application/vnd.github+json' }
            Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile $Zip -Headers $headers -TimeoutSec 120
            Expand-Archive -LiteralPath $Zip -DestinationPath $Dir -Force
            $ok = $true
            Say "   Da tai tu: $u"
            break
        } catch {
            Say "   Thu $u that bai: $($_.Exception.Message)"
        }
    }
    if (-not $ok) {
        Say ''
        Say '   KHONG TAI DUOC BAN MOI (khong co Internet / PowerShell bi chan).'
        Say '   CACH CHAC CHAN NHAT: copy ca thu muc tool tu o Z:'
        Say '     Z:\HQData-2\TOOLS TONG HOP\TOOLS UPDATE CUOI\News_Clip_Stitcher'
        Say '   chep de len thu muc hien tai, GIU LAI config.json cu.'
        return $false
    }

    Say '   Dang chep de (giu config.json cu)...'
    if (Test-Path (Join-Path $Base 'config.json')) {
        Copy-Item (Join-Path $Base 'config.json') $Keep -Force
    }
    $root = Get-ChildItem -LiteralPath $Dir -Directory | Select-Object -First 1
    if (-not $root) { $root = Get-Item -LiteralPath $Dir }
    Copy-Item -Path (Join-Path $root.FullName '*') -Destination $Base -Recurse -Force
    if (Test-Path $Keep) { Copy-Item $Keep (Join-Path $Base 'config.json') -Force }
    Remove-Item $Keep -Force -ErrorAction SilentlyContinue
    Remove-Item $Zip  -Force -ErrorAction SilentlyContinue
    Remove-Item $Dir  -Recurse -Force -ErrorAction SilentlyContinue

    $m = Join-Path $Base 'main.py'
    if (-not (Test-Path $m)) { Say '   LOI: chep de xong nhung thieu main.py.'; return $false }
    Say '   Da chep de xong.'
    return $true
}

# ---------------------------------------------------------------- main
Say ''
$Py = Find-Python
if ($Py) { Say "Python: $Py" } else { Say 'Python: KHONG TIM THAY' }
Say ''

# --- cach A
Say '[Cach 1/2] Chay updater.py (tu dung kho chung chi cua may)...'
if (Test-Path $Pem) {
    Say '   Da co san cacert.pem'
} else {
    foreach ($u in @($RawPem, $ApiPem)) {
        try {
            if ($u -eq $ApiPem) {
                $j = Invoke-RestMethod -UseBasicParsing -Uri $u -TimeoutSec 60 `
                        -Headers @{ 'Accept' = 'application/vnd.github+json' }
                [IO.File]::WriteAllBytes($Pem, [Convert]::FromBase64String(($j.content -replace '\s', '')))
            } else {
                Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile $Pem -TimeoutSec 60
            }
            Say '   Da tai cacert.pem'
            break
        } catch {
            Say "   Chua tai duoc chung chi ($u)"
        }
    }
}

if ($Py) {
    Say '   Dang cap nhat bang updater.py...'
    if (Test-Path $Pem) {
        $env:SSL_CERT_FILE      = $Pem
        $env:REQUESTS_CA_BUNDLE = $Pem
    }
    Push-Location $Base
    & $Py 'updater.py' '--apply'
    $rc = $LASTEXITCODE
    Pop-Location
    if ($rc -eq 0) {
        Say ''
        Say '============================================================'
        Say '  XONG. Mo lai tool de dung ban moi.'
        Say '============================================================'
        exit 0
    }
    Say "   Cach 1 that bai (ma loi $rc), chuyen cach 2..."
} else {
    Say '   Khong co Python -> chuyen thang cach 2.'
}

if (Get-WholeTool) {
    Say ''
    Say '============================================================'
    Say '  XONG. Mo lai tool de dung ban moi.'
    Say '============================================================'
    exit 0
}

Say ''
Say '============================================================'
Say '  SUA TU DONG KHONG DUOC. Lam theo cach sau:'
Say '  1. Mo o Z:  Z:\HQData-2\TOOLS TONG HOP\TOOLS UPDATE CUOI'
Say '  2. Copy ca thu muc News_Clip_Stitcher ve may nay'
Say '  3. Chep de len thu muc tool hien tai'
Say '  4. GIU LAI file config.json cu (dung ghi de)'
Say '============================================================'
exit 1
