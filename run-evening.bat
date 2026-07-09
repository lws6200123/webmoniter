@echo off
cd /d d:\vibecoding\information\web-monitor
echo [%date% %time%] Evening run started >> data\cron.log
C:\Python314\python.exe main.py run --evening >> data\cron.log 2>&1
echo [%date% %time%] Evening run finished (exit code: %ERRORLEVEL%) >> data\cron.log
