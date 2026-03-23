@echo off
REM ============================================================
REM  Sysprep Generalize — Windows 11 Image
REM
REM  Run this AFTER pre-sysprep.ps1 has completed.
REM  The unattend.xml must be placed alongside this script
REM  or update the path below.
REM ============================================================

set UNATTEND=%~dp0unattend.xml

echo.
echo  Verifying unattend.xml exists at: %UNATTEND%
if not exist "%UNATTEND%" (
    echo  ERROR: unattend.xml not found. Place it next to this script.
    pause
    exit /b 1
)

echo.
echo  Starting Sysprep /generalize /oobe /shutdown ...
echo  The machine will SHUT DOWN when finished.
echo  Press Ctrl+C now to abort.
echo.
timeout /t 10

C:\Windows\System32\Sysprep\sysprep.exe /generalize /oobe /shutdown /unattend:"%UNATTEND%"

if %ERRORLEVEL% neq 0 (
    echo.
    echo  Sysprep failed with exit code %ERRORLEVEL%.
    echo  Check C:\Windows\System32\Sysprep\Panther\setuperr.log
    pause
)
