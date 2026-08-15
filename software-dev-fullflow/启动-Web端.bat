@echo off
rem 双击启动「Web 端入口」—— 官方 AgentTeams Dashboard（自动打开浏览器）
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "scripts\entry-web.ps1"
echo.
pause
