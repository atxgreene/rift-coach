@echo off
title Macro Goblin
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 (
  echo Python is not on PATH. Do not install anything until you say so.
  pause
  exit /b 1
)
echo.
echo  Macro Goblin
echo  League must be Borderless, not exclusive Fullscreen.
echo  Drag the Macro Goblin card anywhere on the second screen.
echo  Ctrl+Shift+M locks/unlocks click-through. Ctrl+Shift+O hides it.
echo  This launch records the match locally. Nothing is uploaded.
echo.
python "%~dp0lol_coach.py" --overlay --capture --log %*
echo.
echo Coach stopped. Match notes, if any, are in reports\
pause
