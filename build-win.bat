@echo off
REM ============================================================
REM  FindWords Windows Build Script
REM  在 Windows 上运行此脚本打包完整安装包
REM ============================================================

echo [1/4] 安装前端依赖...
cd /d "%~dp0frontend"
call npm install
if errorlevel 1 (
    echo 前端依赖安装失败
    exit /b 1
)

echo [2/4] 构建前端...
call npm run build
if errorlevel 1 (
    echo 前端构建失败
    exit /b 1
)

echo [3/4] 构建后端可执行文件...
cd /d "%~dp0backend"
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --clean --noconfirm findwords-server.spec
if errorlevel 1 (
    echo 后端构建失败
    exit /b 1
)

echo [4/4] 打包 Windows 安装包...
cd /d "%~dp0frontend"
call npx electron-builder --win
if errorlevel 1 (
    echo 打包失败
    exit /b 1
)

echo.
echo ========================================
echo  构建完成！安装包位于 frontend/release/
echo ========================================
echo.
echo 安装后数据存储位置:
echo   %%APPDATA%%\FindWords\data\
echo   包含: findwords.db (数据库), config.json (配置), uploads/ (上传文件)
echo.
pause
