@echo off
cd /d d:\vibecoding\information\web-monitor

REM 用法: push-to-remote.bat https://gitee.com/你的用户名/仓库名.git
if "%1"=="" (
    echo 用法: push-to-remote.bat <远程仓库地址>
    echo 示例: push-to-remote.bat https://gitee.com/wsl/web-monitor.git
    exit /b 1
)

git remote remove origin 2>nul
git remote add origin %1
git push -u origin master
echo ✅ 推送完成: %1
