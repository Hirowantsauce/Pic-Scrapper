@echo off
title Push to GitHub
cd /d "%~dp0"
echo ===================================================
echo  Pushing Wallpics to GitHub (Hirowantsauce/Pic-Scrapper)
echo ===================================================
echo.
git push -u origin main
if %ERRORLEVEL% neq 0 (
    if exist "C:\Users\fironite\AppData\Local\Programs\Git\cmd\git.exe" (
        "C:\Users\fironite\AppData\Local\Programs\Git\cmd\git.exe" push -u origin main
    )
)
echo.
if %ERRORLEVEL% equ 0 (
    echo ===================================================
    echo  Successfully pushed to GitHub!
    echo ===================================================
) else (
    echo.
    echo If authentication failed, you can generate a Personal Access Token (PAT)
    echo on GitHub at https://github.com/settings/tokens with 'repo' scope.
)
pause
