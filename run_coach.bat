@echo off
title Macro Goblin
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 (
  echo Python is not on PATH. Install Python 3.9+ from python.org and tick "Add to PATH".
  pause
  exit /b 1
)
echo.
echo  Macro Goblin
echo  League must be Borderless, not exclusive Fullscreen.
echo  Drag the card where you want it. Ctrl+Shift+M locks click-through. Ctrl+Shift+O hides it.
echo  This launch records the match locally (captures\). Nothing is uploaded.
echo.
python "%~dp0lol_coach.py" --overlay --capture --log %*
echo.
echo Coach stopped. Match notes are in reports\
pause
