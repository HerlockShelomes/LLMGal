@echo off
setlocal

rem Windows compatibility wrapper. Prefer the Python launcher when present.
where py >nul 2>nul
if %errorlevel% EQU 0 (
    py -3 "%~dp0run_module1_tests.py" %*
    exit /b %errorlevel%
)

python "%~dp0run_module1_tests.py" %*
exit /b %errorlevel%
