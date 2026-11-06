@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

:: ========================================================
:: DeepSeek API Client - Environment Setup (v2.2)
:: 修改：在 deal_vedio 目录创建 .venv 虚拟环境
:: ========================================================

:: 获取脚本所在目录（client目录），然后获取父目录（deal_vedio）
set "CLIENT_DIR=%~dp0"
set "CLIENT_DIR=%CLIENT_DIR:~0,-1%"
set "PROJECT_ROOT=%CLIENT_DIR%\.."
set "PROJECT_ROOT=%PROJECT_ROOT:\..\..=%"

:: 标准化路径，去除可能的相对路径
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"

echo ========================================================
echo  DeepSeek API Client - Environment Setup (v2.2)
echo  Project Root: %PROJECT_ROOT%
echo  Client Dir: %CLIENT_DIR%
echo  Note: Virtual environment will be created in project root
echo ========================================================
echo.

:: 检查 Python
python --version 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found in PATH.
    echo        Please install Python 3.8 or higher from:
    echo        https://www.python.org/downloads/
    exit /b 1
)

:: 获取 Python 版本
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYTHON_VER=%%v"
echo Detected Python version: %PYTHON_VER%

:: 检查 Python 3.x
echo %PYTHON_VER% | findstr /r "^3\." >nul
if %errorlevel% neq 0 (
    echo [ERROR] Python 2.x detected. This script requires Python 3.x.
    exit /b 1
)

echo [INFO] Python 3.x detected - compatible version.
echo.

:: 设置虚拟环境路径（在 deal_vedio 目录下）
set "VENV_DIR=%PROJECT_ROOT%\.venv"
echo Creating virtual environment at:
echo   %VENV_DIR%
echo.

:: 创建虚拟环境
if exist "%VENV_DIR%" (
    echo [INFO] Removing existing virtual environment...
    rmdir /s /q "%VENV_DIR%" >nul 2>&1
)

echo [INFO] Creating new virtual environment...
python -m venv "%VENV_DIR%"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create virtual environment
    exit /b 1
)

echo Virtual environment created successfully!
echo.

:: 激活并安装依赖
call "%VENV_DIR%\Scripts\activate.bat"

echo Installing core dependencies (including OpenAI SDK)...
pip install --upgrade pip >nul 2>&1

:: 安装依赖
pip install "openai>=1.28.0,<2.0.0" "requests>=2.25.0,<3.0.0" "keyring>=23.0.0,<26.0.0" "cryptography>=3.4.0,<44.0.0" >nul 2>&1

if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies
    echo        Trying to show detailed error...
    pip install "openai>=1.28.0,<2.0.0" "requests>=2.25.0,<3.0.0" "keyring>=23.0.0,<26.0.0" "cryptography>=3.4.0,<44.0.0"
    call deactivate >nul 2>&1
    exit /b 1
)

echo Dependencies installed successfully!
echo.

:: 验证安装
echo Verifying installation:
pip list --format=columns | findstr /i "openai requests keyring cryptography"
echo.

:: 生成 requirements.txt（在 client 目录下）
pip freeze > "%CLIENT_DIR%\requirements.txt"
echo requirements.txt created at: %CLIENT_DIR%\requirements.txt
echo.

:: 创建激活脚本（在 client 目录下）
echo Creating activation script...
(
echo @echo off
echo call "%%~dp0..\.venv\Scripts\activate.bat"
echo echo Virtual environment activated.
echo echo Project root: %PROJECT_ROOT%
) > "%CLIENT_DIR%\activate.bat"

(
echo # PowerShell activation script
echo "& '%~dp0..\.venv\Scripts\Activate.ps1'"
echo "Write-Host 'Virtual environment activated.' -ForegroundColor Green"
echo "Write-Host 'Project root: %PROJECT_ROOT%' -ForegroundColor Cyan"
) > "%CLIENT_DIR%\activate.ps1"

echo Activation scripts created:
echo   - activate.bat ^(Command Prompt^)
echo   - activate.ps1 ^(PowerShell^)
echo.

:: 清理并退出
call deactivate >nul 2>&1

echo ========================================================
echo  SETUP COMPLETE! (v2.2)
echo.
echo  Successfully installed:
echo  - OpenAI SDK (for DeepSeek API compatibility)
echo  - Requests, Keyring, Cryptography
echo.
echo  Virtual environment location: %VENV_DIR%
echo  Client directory: %CLIENT_DIR%
echo.
echo  Next steps:
echo  1. Navigate to client directory: cd %CLIENT_DIR%
echo  2. Activate environment: .\activate.bat ^(or .\activate.ps1^)
echo  3. Continue with project development
echo ========================================================

endlocal
exit /b 0