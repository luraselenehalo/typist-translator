@echo off
REM Typist Translator - launcher
REM Builds the React UI on first run, then starts the app.
cd /d "%~dp0"

if not exist "ui\dist\index.html" (
    echo [run] Building the UI for the first time...
    pushd ui
    call npm install --no-fund --no-audit
    call npm run build
    popd
)

python main.py
if errorlevel 1 pause
