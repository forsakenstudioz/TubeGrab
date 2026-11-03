@echo off
chcp 65001 >nul
title Build TubeGrab.exe
cd /d "%~dp0"

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY set "PY=python"

echo Installing / updating build tools...
%PY% -m pip install -U pyinstaller "yt-dlp[default]" || goto :fail

echo Building TubeGrab.exe ...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name TubeGrab ^
  --icon assets\tubegrab.ico --add-data "assets\tubegrab.ico;assets" tubegrab.py || goto :fail

rem Make a ready-to-share folder
if not exist "share" mkdir "share"
copy /y "dist\TubeGrab.exe" "share\" >nul
copy /y "Install-Tools.bat" "share\" >nul
copy /y "README.md" "share\" >nul
copy /y "LICENSE" "share\" >nul

echo.
echo Done! The "share" folder has everything to give to friends.
echo Tip: for a fully portable folder, also copy ffmpeg.exe, ffprobe.exe and deno.exe into "share".
echo      TubeGrab finds them next to the .exe automatically - no install needed.
pause
exit /b 0

:fail
echo Build failed - see the messages above.
pause
exit /b 1
