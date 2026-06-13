@echo off
REM 课堂喊人传话系统 v2.0 - 启动脚本
REM 双击运行即可
REM 如需修改端口，把下面的 9000 改成你想要的数字

set PORT=9000

cd /d "%~dp0"
call venv\Scripts\activate.bat
echo.
echo 启动中... 端口: %PORT%
echo.
python server.py %PORT%
pause
