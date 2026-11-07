@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 找不到 .venv，请先按 AGENTS.md 第 1 节准备环境
    pause
    exit /b 1
)

echo ================================================
echo  运行单元测试
echo ================================================
.venv\Scripts\python -m unittest discover -s tests -v
set CODE=%ERRORLEVEL%

echo.
if %CODE%==0 (
    echo [通过] 全部测试通过
) else (
    echo [失败] 退出码 %CODE%
)
pause
exit /b %CODE%
