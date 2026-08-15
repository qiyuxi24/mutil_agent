@echo off
rem ============================================================
rem  AgentTeams 项目一键启动菜单
rem  双击本文件即可选择入口：
rem     1. 命令行入口（官方 agt CLI + 任务派发）
rem     2. Web 端入口（官方 AgentTeams Dashboard）
rem ============================================================
setlocal
cd /d "%~dp0"

:menu
cls
echo.
echo  =============================================
echo   软件研发全流程协同 Agent 团队 · 启动菜单
echo  =============================================
echo.
echo    1. 命令行入口（agt CLI + 提交任务）
echo    2. Web 端入口（官方 Dashboard）
echo    0. 退出
echo.
set /p choice="  请选择 (1/2/0): "

if "%choice%"=="1" goto cli
if "%choice%"=="2" goto web
if "%choice%"=="0" exit /b 0
goto menu

:cli
echo.
echo  启动命令行入口...
powershell -ExecutionPolicy Bypass -File "scripts\entry-cli.ps1"
echo.
echo  命令行入口已退出。
pause
goto menu

:web
echo.
echo  启动 Web 端入口...
powershell -ExecutionPolicy Bypass -File "scripts\entry-web.ps1"
echo.
pause
goto menu
