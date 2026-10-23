@echo off
chcp 65001 >nul
title TubeGrab - install tools
echo This installs the free tools TubeGrab needs, using winget (built into Windows 10/11):
echo   - FFmpeg  : merges video+audio, makes MP3s, embeds covers/subtitles
echo   - Deno    : lets yt-dlp solve YouTube's JavaScript challenges
echo   - Python  : only needed if you run tubegrab.py instead of TubeGrab.exe
echo.
where winget >nul 2>&1 || (
  echo winget was not found. Install "App Installer" from the Microsoft Store, then run this again.
  pause & exit /b 1
)
winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
winget install --id DenoLand.Deno -e --accept-source-agreements --accept-package-agreements
if not exist "%~dp0TubeGrab.exe" (
  where python >nul 2>&1 || winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
)
echo.
echo Done. Close this window, then start TubeGrab again so it picks up the new tools.
pause
