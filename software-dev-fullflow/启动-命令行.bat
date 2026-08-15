@echo off
rem 双击启动「命令行入口」—— AgentTeams 官方 agt CLI + 任务派发
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "scripts\entry-cli.ps1"
echo.
pause
