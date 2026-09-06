@echo off
REM Rebuild the React UI after changing anything under ui\src
cd /d "%~dp0\ui"
call npm run build
