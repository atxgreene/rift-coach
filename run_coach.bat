@echo off
title Rift Coach
cd /d "%~dp0"
echo Rift Coach: set League to Borderless (not exclusive Fullscreen) so the overlay can draw.
python "%~dp0lol_coach.py" --overlay %*
echo.
echo Coach stopped.
pause
