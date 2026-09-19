@echo off
setlocal EnableDelayedExpansion
REM =====================================================================
REM LLMGal 后端环境一键部署（Windows 原生）
REM 前置：Python 3.11–3.14（py 启动器）+ 可选 Node.js 18+（前端）
REM =====================================================================
set "PROJECT_ROOT=%~dp0.."
set "BACKEND=%PROJECT_ROOT%\backend"
set "VENV=%BACKEND%\.venv"

echo [1/4] 查找 Python 3.11–3.14 ...
set "PYTHON_VERSION="
for %%V in (3.14 3.13 3.12 3.11) do (
  if not defined PYTHON_VERSION (
    py -%%V --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_VERSION=%%V"
  )
)
if not defined PYTHON_VERSION (
  echo 错误：未找到 Python 3.11–3.14（py 启动器）。请安装兼容版本后重试。
  exit /b 1
)
py -%PYTHON_VERSION% --version

if not exist "%VENV%\" (
  echo [2/4] 创建虚拟环境 %VENV% ...
  py -%PYTHON_VERSION% -m venv "%VENV%"
)

call "%VENV%\Scripts\activate.bat"
python -m pip install --upgrade pip
echo [3/4] 安装后端依赖 backend\requirements.txt ...
pip install -r "%BACKEND%\requirements.txt"

REM 火山旧版图像 SDK 不自动安装：其上游依赖在 Python 3.14 不兼容。

if not exist "%BACKEND%\.env" (
  if exist "%BACKEND%\.env.example" (
    copy "%BACKEND%\.env.example" "%BACKEND%\.env" >nul
    echo 已复制 .env.example -^> .env，请填入你的 API 密钥（勿提交）。
  )
)

set "DO_TEST=N"
set /p DO_TEST=是否安装测试依赖(requirements-test.txt)? [y/N] 
if /i "!DO_TEST!"=="y" (
  pip install -r "%BACKEND%\requirements-test.txt"
)

set "DO_FE=N"
set /p DO_FE=是否安装前端依赖(npm ci)? [y/N] 
if /i "!DO_FE!"=="y" (
  echo [4/4] 安装前端依赖 ...
  pushd "%PROJECT_ROOT%\frontend"
  call npm ci
  popd
) else (
  echo [4/4] 跳过前端依赖（稍后可 cd frontend ^&^& npm ci）。
)

echo.
echo 部署完成。
echo   后端: cd backend ^&^& uvicorn Connect:app --reload --host 127.0.0.1 --port 8000
echo   前端: cd frontend ^&^& npm run dev
endlocal
