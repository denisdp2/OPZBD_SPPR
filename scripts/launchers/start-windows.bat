@echo off
rem Run the program from a USB drive. Data is stored in the "data" folder next to this file.
chcp 65001 >nul
cd /d "%~dp0"
set "SZI_DATA_DIR=%~dp0data"
"%~dp0szi\szi.exe" %*
if errorlevel 1 pause
