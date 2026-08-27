@echo off
title YouTube Shorts 100%% Autonomous Engine
cd /d "C:\Users\jisha\OneDrive\Desktop\yt automation"

:loop
echo [%date% %time%] Starting autonomous Shorts daemon... >> autopilot.log
"C:\Users\jisha\AppData\Local\Programs\Python\Python313\python.exe" main.py --daemon >> autopilot.log 2>&1
echo [%date% %time%] Daemon stopped or crashed. Restarting in 60 seconds... >> autopilot.log
timeout /t 60 /nobreak >nul
goto loop
