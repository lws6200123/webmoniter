@echo off
cd /d d:\vibecoding\information\web-monitor
echo [%date% %time%] Morning run started >> data\cron.log
C:\Python314\python.exe main.py run --morning >> data\cron.log 2>&1
echo [%date% %time%] Morning run finished (exit code: %ERRORLEVEL%) >> data\cron.log
