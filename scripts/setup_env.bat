@echo off
setlocal EnableDelayedExpansion
REM =====================================================================
REM LLMGal 后端环境一键部署（Windows 原生）
REM 前置：Python 3.11（py 启动器）+ 可选 Node.js 18+（前端）
REM 若你的 Python 3.11 不是通过 py 启动器安装，请改用 scripts/setup_env.sh
REM 并指定 LLMGAL_PYTHON，或手动把下面所有的 py -3.11 改成你的解释器路径。
REM =====================================================================
set "PROJECT_ROOT=%~dp0.."
set "BACKEND=%PROJECT_ROOT%\backend"
set "VENV=%BACKEND%\.venv"

echo [1/4] 检查 Python 3.11 ...
py -3.11 --version >nul 2>&1
if errorlevel 1 (
  echo 错误：未找到 Python 3.11（py 启动器）。请安装 Python 3.11，或改用 setup_env.sh。
  exit /b 1
)

if not exist "%VENV%\" (
  echo [2/4] 创建虚拟环境 %VENV% ...
  py -3.11 -m venv "%VENV%"
)

call "%VENV%\Scripts\activate.bat"
python -m pip install --upgrade pip
echo [3/4] 安装后端依赖 backend\requirements.txt ...
pip install -r "%BACKEND%\requirements.txt"

REM volcengine 元数据硬钉 pycryptodome==3.9.9（cp311 无轮子，需 VC++ 编译）。
REM 用 --no-deps 安装，避免 pip 把它拉回 3.9.9 源码编译失败；pycryptodome 3.21.0
REM 已由 requirements.txt 先行装好（abi3 轮子，cp311 可直接安装）。
echo 安装 volcengine==1.0.192 (--no-deps，绕过 pycryptodome 过度钉版本) ...
pip install --no-deps volcengine==1.0.192

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
