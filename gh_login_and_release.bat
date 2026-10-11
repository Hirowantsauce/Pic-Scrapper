@echo off
title GitHub CLI Authentication & Release Uploader
cd /d "%~dp0"
where gh >nul 2>nul
if %ERRORLEVEL% neq 0 (
    set "PATH=%PATH%;C:\Users\fironite\AppData\Local\Programs\gh;C:\Users\fironite\AppData\Local\Programs\Git\cmd"
)

echo ========================================================
echo  Step 1: Logging in to GitHub CLI
echo ========================================================
echo.
gh auth login

echo.
echo ========================================================
echo  Step 2: Uploading Wallpics-v1.0.0.exe to GitHub Releases
echo ========================================================
echo.

gh release create v1.0.0 "dist\Wallpics-v1.0.0.exe" --repo Hirowantsauce/Pic-Scrapper --title "Wallpics PRO v1.0.0 (Windows)" --notes "Standalone single-file executable for Windows. Download images at maximum resolution with real-time progress tracking."

if %ERRORLEVEL% neq 0 (
    echo.
    echo Release might already exist, attempting upload...
    gh release upload v1.0.0 "dist\Wallpics-v1.0.0.exe" --repo Hirowantsauce/Pic-Scrapper --clobber
)

echo.
echo ========================================================
echo  Done! Check: https://github.com/Hirowantsauce/Pic-Scrapper/releases
echo ========================================================
pause
